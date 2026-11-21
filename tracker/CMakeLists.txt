cmake_minimum_required(VERSION 3.20)

project(focus_tracker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# PostgreSQL client library (libpq). By default the newest version under
# C:/Program Files/PostgreSQL is used; override with -DPG_ROOT=<path>.
if(NOT PG_ROOT)
    file(GLOB _pg_versions LIST_DIRECTORIES true "C:/Program Files/PostgreSQL/*")
    list(SORT _pg_versions COMPARE NATURAL ORDER DESCENDING)
    list(GET _pg_versions 0 PG_ROOT)
endif()
find_path(PG_INCLUDE_DIR libpq-fe.h HINTS "${PG_ROOT}/include" REQUIRED)
# Link the DLL's import library (libpq.lib). Not libpq.a: on Windows that is
# an MSVC-built static archive that drags in PostgreSQL internals.
find_library(PG_LIBRARY NAMES libpq.lib pq HINTS "${PG_ROOT}/lib" NO_DEFAULT_PATH REQUIRED)
message(STATUS "Using PostgreSQL from ${PG_ROOT}")

find_package(Threads REQUIRED)

add_executable(focus_tracker
    src/main.cpp
    src/notifier.cpp
    src/async_writer.cpp
    src/focus_mode.cpp
    src/idle_detector.cpp
    src/pg_db_client.cpp
    src/process_monitor.cpp
    src/session_manager.cpp
    src/types.cpp
    src/window_monitor.cpp
)

target_include_directories(focus_tracker PRIVATE include "${PG_INCLUDE_DIR}")
target_link_libraries(focus_tracker PRIVATE "${PG_LIBRARY}" Threads::Threads)

if(WIN32)
    target_compile_definitions(focus_tracker PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
    target_link_libraries(focus_tracker PRIVATE user32 psapi shell32)
endif()

if(MINGW)
    # Bundle libstdc++/libgcc/winpthread so only libpq's DLLs are needed.
    target_link_options(focus_tracker PRIVATE -static)
endif()

if(MSVC)
    target_compile_options(focus_tracker PRIVATE /W4 /utf-8)
else()
    target_compile_options(focus_tracker PRIVATE -Wall -Wextra)
endif()

# Unit tests (no database or Win32 needed):  ctest --test-dir build
enable_testing()
add_executable(focus_tests tests/test_main.cpp src/session_manager.cpp src/types.cpp)
target_include_directories(focus_tests PRIVATE include)
target_link_libraries(focus_tests PRIVATE Threads::Threads)
if(MINGW)
    target_link_options(focus_tests PRIVATE -static)
endif()
if(NOT MSVC)
    target_compile_options(focus_tests PRIVATE -Wall -Wextra)
endif()
add_test(NAME focus_tests COMMAND focus_tests)

# libpq.dll and the DLLs it depends on (OpenSSL, zlib, ...) must sit next to
# the .exe, or PostgreSQL's bin folder must be on PATH.
if(WIN32)
    file(GLOB PG_RUNTIME_DLLS
        "${PG_ROOT}/bin/libpq.dll"
        "${PG_ROOT}/bin/libintl-*.dll"
        "${PG_ROOT}/bin/libiconv-*.dll"
        "${PG_ROOT}/bin/libssl-*.dll"
        "${PG_ROOT}/bin/libcrypto-*.dll")
    add_custom_command(TARGET focus_tracker POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different ${PG_RUNTIME_DLLS} "$<TARGET_FILE_DIR:focus_tracker>"
        COMMENT "Copying PostgreSQL client DLLs")
endif()
