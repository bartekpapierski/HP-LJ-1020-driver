# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.25)

project(hp_lj_1020 VERSION 0.1.0 LANGUAGES C)

set(HPLJ1020_LOCKED_DEPENDENCIES "" CACHE FILEPATH "Generated locked source inventory")
if(NOT HPLJ1020_LOCKED_DEPENDENCIES OR NOT EXISTS "${HPLJ1020_LOCKED_DEPENDENCIES}")
  message(FATAL_ERROR "Configure through scripts/build so locked sources are verified")
endif()
include("${HPLJ1020_LOCKED_DEPENDENCIES}")
foreach(source IN LISTS HPLJ1020_LOCKED_SOURCE_FILES)
  list(GET HPLJ1020_LOCKED_SOURCE_HASHES ${HPLJ1020_LOCKED_SOURCE_INDEX} expected_hash)
  file(SHA256 "${source}" actual_hash)
  if(NOT actual_hash STREQUAL expected_hash)
    message(FATAL_ERROR "Locked source hash mismatch: ${source}")
  endif()
  math(EXPR HPLJ1020_LOCKED_SOURCE_INDEX "${HPLJ1020_LOCKED_SOURCE_INDEX} + 1")
endforeach()
add_custom_target(locked-sources ALL DEPENDS ${HPLJ1020_LOCKED_SOURCE_FILES})

if(NOT APPLE OR NOT CMAKE_SYSTEM_PROCESSOR STREQUAL "arm64")
  message(FATAL_ERROR "HP LJ 1020 currently supports only Apple Silicon (arm64)")
endif()

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_OSX_ARCHITECTURES arm64 CACHE STRING "Supported architecture" FORCE)

add_library(hplj1020_build_options INTERFACE)
target_compile_options(hplj1020_build_options INTERFACE
  -Wall -Wextra -Wpedantic -Werror)

add_library(hplj1020_core
  src/device.c
  src/encoder.c
  src/error.c
  src/firmware.c
  src/firmware_store.c
  src/pappl.c
  src/version.c)
target_include_directories(hplj1020_core PUBLIC include)
target_link_libraries(hplj1020_core PRIVATE hplj1020_build_options)

add_executable(hplj1020 src/main.c)
target_link_libraries(hplj1020 PRIVATE hplj1020_build_options hplj1020_core)
add_dependencies(hplj1020 locked-sources)

include(CTest)
if(BUILD_TESTING)
  add_executable(hplj1020-smoke tests/smoke.c)
  target_link_libraries(hplj1020-smoke PRIVATE hplj1020_build_options)
  add_test(NAME hplj1020-smoke COMMAND hplj1020-smoke)
  add_executable(hplj1020-contracts tests/contracts.c)
  target_link_libraries(hplj1020-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-contracts COMMAND hplj1020-contracts)
  add_executable(hplj1020-firmware-contracts tests/firmware_contracts.c)
  target_include_directories(hplj1020-firmware-contracts PRIVATE tests)
  target_link_libraries(hplj1020-firmware-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-firmware-contracts COMMAND hplj1020-firmware-contracts)
  add_test(NAME hplj1020-version COMMAND hplj1020 --version)
  set_tests_properties(hplj1020-version PROPERTIES
    PASS_REGULAR_EXPRESSION "hplj1020 0\\.1\\.0")
endif()
