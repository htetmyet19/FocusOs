#pragma once

#include <mysql.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <string>
#include <utility>

#include "segment.h"

class DbClient {
public:
    struct Config {
        std::string host = "127.0.0.1";
        unsigned int port = 3306;
        std::string user;
        std::string password;
        std::string database = "study_tracker";
    };

    explicit DbClient(Config config)
        : config_(std::move(config)) {}

    ~DbClient() {
        disconnect();
    }

    DbClient(const DbClient&) = delete;
    DbClient& operator=(const DbClient&) = delete;

    bool connect(std::string& error) {
        error.clear();

        if (connection_ != nullptr) {
            return true;
        }

        connection_ = mysql_init(nullptr);

        if (connection_ == nullptr) {
            error = "mysql_init() failed.";
            return false;
        }

        unsigned int timeout_seconds = 5;
        mysql_options(
            connection_,
            MYSQL_OPT_CONNECT_TIMEOUT,
            &timeout_seconds
        );

        if (mysql_real_connect(
                connection_,
                config_.host.c_str(),
                config_.user.c_str(),
                config_.password.c_str(),
                config_.database.c_str(),
                config_.port,
                nullptr,
                0
            ) == nullptr) {
            error = mysql_error(connection_);
            disconnect();
            return false;
        }

        if (mysql_set_character_set(connection_, "utf8mb4") != 0) {
            error = mysql_error(connection_);
            disconnect();
            return false;
        }

        return true;
    }

    void disconnect() {
        if (connection_ != nullptr) {
            mysql_close(connection_);
            connection_ = nullptr;
        }
    }

    bool startSession(long long& session_id, std::string& error) {
        if (!ensureConnected(error)) {
            return false;
        }

        const char* sql =
            "INSERT INTO sessions (start_time) VALUES (UTC_TIMESTAMP())";

        if (mysql_query(connection_, sql) != 0) {
            error = mysql_error(connection_);
            return false;
        }

        session_id = static_cast<long long>(mysql_insert_id(connection_));

        if (session_id <= 0) {
            error = "MySQL did not return a valid session ID.";
            return false;
        }

        return true;
    }

    bool insertSegment(
        long long session_id,
        const Segment& segment,
        std::string& error
    ) {
        if (!ensureConnected(error)) {
            return false;
        }

        MYSQL_TIME start_time = toMysqlDateTime(segment.start_time);
        MYSQL_TIME end_time = toMysqlDateTime(segment.end_time);

        long long database_session_id = session_id;
        std::uint32_t process_id = segment.process_id;
        long long duration_seconds = segment.duration_seconds;

        unsigned long process_name_length =
            static_cast<unsigned long>(segment.process_name.size());

        unsigned long window_title_length =
            static_cast<unsigned long>(segment.window_title.size());

        unsigned long category_length =
            static_cast<unsigned long>(segment.category.size());

        MYSQL_BIND bindings[8]{};

        bindings[0].buffer_type = MYSQL_TYPE_LONGLONG;
        bindings[0].buffer = &database_session_id;

        bindings[1].buffer_type = MYSQL_TYPE_LONG;
        bindings[1].buffer = &process_id;
        bindings[1].is_unsigned = true;

        bindings[2].buffer_type = MYSQL_TYPE_STRING;
        bindings[2].buffer = const_cast<char*>(segment.process_name.data());
        bindings[2].buffer_length = process_name_length;
        bindings[2].length = &process_name_length;

        bindings[3].buffer_type = MYSQL_TYPE_STRING;
        bindings[3].buffer = const_cast<char*>(segment.window_title.data());
        bindings[3].buffer_length = window_title_length;
        bindings[3].length = &window_title_length;

        bindings[4].buffer_type = MYSQL_TYPE_DATETIME;
        bindings[4].buffer = &start_time;

        bindings[5].buffer_type = MYSQL_TYPE_DATETIME;
        bindings[5].buffer = &end_time;

        bindings[6].buffer_type = MYSQL_TYPE_LONGLONG;
        bindings[6].buffer = &duration_seconds;

        bindings[7].buffer_type = MYSQL_TYPE_STRING;
        bindings[7].buffer = const_cast<char*>(segment.category.data());
        bindings[7].buffer_length = category_length;
        bindings[7].length = &category_length;

        const char* sql =
            "INSERT INTO activity_logs ("
            "session_id, process_id, process_name, window_title, "
            "start_time, end_time, duration_seconds, category"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)";

        return executePrepared(sql, bindings, 8, error);
    }

    bool endSession(long long session_id, std::string& error) {
        if (!ensureConnected(error)) {
            return false;
        }

        long long database_session_id = session_id;

        MYSQL_BIND bindings[1]{};

        bindings[0].buffer_type = MYSQL_TYPE_LONGLONG;
        bindings[0].buffer = &database_session_id;
        bindings[0].is_unsigned = false;

        const char* sql =
            "UPDATE sessions "
            "SET end_time = UTC_TIMESTAMP() "
            "WHERE id = ?";

        return executePrepared(sql, bindings, 1, error);
    }

private:
    Config config_;
    MYSQL* connection_ = nullptr;

    bool ensureConnected(std::string& error) const {
        if (connection_ == nullptr) {
            error = "Database is not connected.";
            return false;
        }

        return true;
    }

    bool executePrepared(
        const char* sql,
        MYSQL_BIND* bindings,
        unsigned long binding_count,
        std::string& error
    ) {
        MYSQL_STMT* statement = mysql_stmt_init(connection_);

        if (statement == nullptr) {
            error = mysql_error(connection_);
            return false;
        }

        if (mysql_stmt_prepare(
                statement,
                sql,
                static_cast<unsigned long>(std::strlen(sql))
            ) != 0) {
            error = mysql_stmt_error(statement);
            mysql_stmt_close(statement);
            return false;
        }

        if (mysql_stmt_param_count(statement) != binding_count) {
            error = "Prepared-statement parameter count does not match.";
            mysql_stmt_close(statement);
            return false;
        }

        if (mysql_stmt_bind_param(statement, bindings) != 0) {
            error = mysql_stmt_error(statement);
            mysql_stmt_close(statement);
            return false;
        }

        if (mysql_stmt_execute(statement) != 0) {
            error = mysql_stmt_error(statement);
            mysql_stmt_close(statement);
            return false;
        }

        mysql_stmt_close(statement);
        return true;
    }

    static MYSQL_TIME toMysqlDateTime(
        const std::chrono::system_clock::time_point& time_point
    ) {
        std::time_t raw_time =
            std::chrono::system_clock::to_time_t(time_point);

        std::tm utc_time{};
        gmtime_s(&utc_time, &raw_time);

        MYSQL_TIME result{};
        result.year = utc_time.tm_year + 1900;
        result.month = utc_time.tm_mon + 1;
        result.day = utc_time.tm_mday;
        result.hour = utc_time.tm_hour;
        result.minute = utc_time.tm_min;
        result.second = utc_time.tm_sec;

        return result;
    }
};