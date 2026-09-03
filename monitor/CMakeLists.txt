cmake_minimum_required(VERSION 3.20)

project(focus_monitor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(focus_monitor monitor.cpp)

target_include_directories(focus_monitor PRIVATE include)
target_link_libraries(focus_monitor PRIVATE user32)