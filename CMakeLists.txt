# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.25)

project(hp_lj_1020 VERSION 0.1.0 LANGUAGES C)

set(HPLJ1020_LOCKED_DEPENDENCIES "" CACHE FILEPATH "Generated locked source inventory")
if(NOT HPLJ1020_LOCKED_DEPENDENCIES OR NOT EXISTS "${HPLJ1020_LOCKED_DEPENDENCIES}")
  message(FATAL_ERROR "Configure through scripts/build so locked sources are verified")
endif()
include("${HPLJ1020_LOCKED_DEPENDENCIES}")
if(NOT EXISTS "${HPLJ1020_PAPPL_PREFIX}/lib/libpappl.a")
  message(FATAL_ERROR "Pinned PAPPL library is missing; configure through scripts/build")
endif()
foreach(source IN LISTS HPLJ1020_LOCKED_SOURCE_FILES)
  list(GET HPLJ1020_LOCKED_SOURCE_HASHES ${HPLJ1020_LOCKED_SOURCE_INDEX} expected_hash)
  file(SHA256 "${source}" actual_hash)
  if(NOT actual_hash STREQUAL expected_hash)
    message(FATAL_ERROR "Locked source hash mismatch: ${source}")
  endif()
  math(EXPR HPLJ1020_LOCKED_SOURCE_INDEX "${HPLJ1020_LOCKED_SOURCE_INDEX} + 1")
endforeach()
add_custom_target(locked-sources ALL DEPENDS ${HPLJ1020_LOCKED_SOURCE_FILES})

if(NOT EXISTS "${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/libusb.h")
  file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/locked")
  file(ARCHIVE_EXTRACT INPUT "${HPLJ1020_LIBUSB_ARCHIVE}"
    DESTINATION "${CMAKE_BINARY_DIR}/locked")
endif()

add_library(hplj1020_libusb STATIC
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/core.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/descriptor.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/hotplug.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/io.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/strerror.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/sync.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/os/darwin_usb.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/os/events_posix.c
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb/os/threads_posix.c)
target_include_directories(hplj1020_libusb SYSTEM PUBLIC
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/libusb
  ${HPLJ1020_LIBUSB_SOURCE_DIR}/Xcode)
find_library(HPLJ1020_COREFOUNDATION_FRAMEWORK CoreFoundation REQUIRED)
find_library(HPLJ1020_IOKIT_FRAMEWORK IOKit REQUIRED)
find_library(HPLJ1020_SECURITY_FRAMEWORK Security REQUIRED)
target_link_libraries(hplj1020_libusb PUBLIC
  ${HPLJ1020_COREFOUNDATION_FRAMEWORK}
  ${HPLJ1020_IOKIT_FRAMEWORK}
  ${HPLJ1020_SECURITY_FRAMEWORK})
add_dependencies(hplj1020_libusb locked-sources)

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
  src/usb_libusb.c
  src/version.c)
target_include_directories(hplj1020_core PUBLIC include)
target_link_libraries(hplj1020_core PRIVATE hplj1020_build_options hplj1020_libusb)

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)
find_library(HPLJ1020_CUPS_LIBRARY cups REQUIRED)
find_library(HPLJ1020_APPKIT_FRAMEWORK AppKit REQUIRED)
find_library(HPLJ1020_SYSTEMCONFIGURATION_FRAMEWORK SystemConfiguration REQUIRED)
find_library(HPLJ1020_PAM_LIBRARY pam REQUIRED)
add_library(hplj1020_pappl STATIC src/pappl_runtime.c)
target_include_directories(hplj1020_pappl PRIVATE "${HPLJ1020_PAPPL_PREFIX}/include")
target_link_libraries(hplj1020_pappl PUBLIC hplj1020_core)
target_link_libraries(hplj1020_pappl PRIVATE
  hplj1020_build_options
  "${HPLJ1020_PAPPL_PREFIX}/lib/libpappl.a"
  ${HPLJ1020_CUPS_LIBRARY}
  ${HPLJ1020_APPKIT_FRAMEWORK}
  ${HPLJ1020_COREFOUNDATION_FRAMEWORK}
  ${HPLJ1020_SYSTEMCONFIGURATION_FRAMEWORK}
  ${HPLJ1020_PAM_LIBRARY}
  OpenSSL::SSL
  OpenSSL::Crypto
  Threads::Threads
  ZLIB::ZLIB
  m)

add_executable(hplj1020 src/main.c)
target_link_libraries(hplj1020 PRIVATE hplj1020_build_options hplj1020_pappl)
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
  add_executable(hplj1020-device-contracts tests/device_contracts.c)
  target_link_libraries(hplj1020-device-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-device-contracts COMMAND hplj1020-device-contracts)
  add_executable(hplj1020-pappl-service-contracts tests/pappl_service_contracts.c)
  target_link_libraries(hplj1020-pappl-service-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-pappl-service-contracts COMMAND hplj1020-pappl-service-contracts)
  add_executable(hplj1020-make-test-raster tests/make_test_raster.c)
  target_link_libraries(hplj1020-make-test-raster PRIVATE
    hplj1020_build_options ${HPLJ1020_CUPS_LIBRARY})
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(NAME hplj1020-pappl-integration
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pappl_integration.py
      $<TARGET_FILE:hplj1020> $<TARGET_FILE:hplj1020-make-test-raster>
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/invalid-resolution.test
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/invalid-quality.test
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/malformed-raster.test)
  set_tests_properties(hplj1020-pappl-integration PROPERTIES
    SKIP_RETURN_CODE 77 TIMEOUT 30)
  add_test(NAME hplj1020-queue-reconciliation
    COMMAND ${Python3_EXECUTABLE} -m unittest tests.test_queue_reconciliation)
  set_tests_properties(hplj1020-queue-reconciliation PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-version COMMAND hplj1020 --version)
  set_tests_properties(hplj1020-version PROPERTIES
    PASS_REGULAR_EXPRESSION "hplj1020 0\\.1\\.0")
endif()
