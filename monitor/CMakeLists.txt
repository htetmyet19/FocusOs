cmake_minimum_required(VERSION 3.20)

project(focus_monitor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(MYSQL_ROOT "C:/Program Files/MySQL/MySQL Server 8.0")

add_executable(focus_monitor monitor.cpp)

target_include_directories(focus_monitor PRIVATE
    include
    "${MYSQL_ROOT}/include"
)

target_link_libraries(focus_monitor PRIVATE
    user32
    ws2_32
    secur32
    "${MYSQL_ROOT}/lib/libmysql.lib"
)

add_custom_command(TARGET focus_monitor POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${MYSQL_ROOT}/lib/libmysql.dll"
    "$<TARGET_FILE_DIR:focus_monitor>"
)