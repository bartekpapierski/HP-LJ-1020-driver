# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.25)

file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/VERSION" HPLJ1020_VERSION)
if(NOT HPLJ1020_VERSION MATCHES "^0\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")
  message(FATAL_ERROR "VERSION must be a pre-1.0 SemVer")
endif()
project(hp_lj_1020 VERSION ${HPLJ1020_VERSION} LANGUAGES C OBJC)

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

if(NOT EXISTS "${HPLJ1020_FOO2ZJS_SOURCE_DIR}/jbig.h")
  file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/locked")
  file(ARCHIVE_EXTRACT INPUT "${HPLJ1020_FOO2ZJS_ARCHIVE}"
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

add_library(hplj1020_foo2zjs STATIC
  ${HPLJ1020_FOO2ZJS_SOURCE_DIR}/jbig.c
  ${HPLJ1020_FOO2ZJS_SOURCE_DIR}/jbig_ar.c
  third_party/foo2zjs/encoder.c)
target_include_directories(hplj1020_foo2zjs PRIVATE
  include ${HPLJ1020_FOO2ZJS_SOURCE_DIR})
add_dependencies(hplj1020_foo2zjs locked-sources)

add_library(hplj1020_core
  src/device.c
  src/diagnostics.c
  src/encoder.c
  src/error.c
  src/firmware.c
  src/firmware_store.c
  src/job.c
  src/media.c
  src/pappl.c
  src/pjl_status.c
  src/usb_libusb.c
  src/version.c)
target_include_directories(hplj1020_core PUBLIC include)
target_compile_definitions(hplj1020_core PUBLIC HPLJ_PRODUCT_VERSION="${PROJECT_VERSION}")
target_link_libraries(hplj1020_core PRIVATE
  hplj1020_build_options hplj1020_libusb hplj1020_foo2zjs)

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
  add_executable(hplj1020-media-contracts tests/media_contracts.c)
  target_link_libraries(hplj1020-media-contracts PRIVATE
    hplj1020_build_options hplj1020_core ${HPLJ1020_CUPS_LIBRARY})
  add_test(NAME hplj1020-media-contracts COMMAND hplj1020-media-contracts)
  add_executable(hplj1020-pjl-status-contracts tests/pjl_status_contracts.c)
  target_link_libraries(hplj1020-pjl-status-contracts PRIVATE
    hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-pjl-status-contracts COMMAND hplj1020-pjl-status-contracts)
  add_executable(hplj1020-smoke tests/smoke.c)
  target_link_libraries(hplj1020-smoke PRIVATE hplj1020_build_options)
  add_test(NAME hplj1020-smoke COMMAND hplj1020-smoke)
  add_executable(hplj1020-contracts tests/contracts.c)
  target_link_libraries(hplj1020-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-contracts COMMAND hplj1020-contracts)
  add_executable(hplj1020-encoder-contracts tests/encoder_contracts.c)
  target_link_libraries(hplj1020-encoder-contracts PRIVATE
    hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-encoder-contracts COMMAND hplj1020-encoder-contracts)
  add_executable(hplj1020-firmware-contracts tests/firmware_contracts.c)
  target_include_directories(hplj1020-firmware-contracts PRIVATE tests)
  target_link_libraries(hplj1020-firmware-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-firmware-contracts COMMAND hplj1020-firmware-contracts)
  add_executable(hplj1020-device-contracts tests/device_contracts.c)
  target_link_libraries(hplj1020-device-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-device-contracts COMMAND hplj1020-device-contracts)
  add_executable(hplj1020-job-lifecycle-contracts
    tests/job_lifecycle_contracts.c)
  target_link_libraries(hplj1020-job-lifecycle-contracts PRIVATE
    hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-job-lifecycle-contracts
    COMMAND hplj1020-job-lifecycle-contracts)
  add_executable(hplj1020-pappl-service-contracts tests/pappl_service_contracts.c)
  target_link_libraries(hplj1020-pappl-service-contracts PRIVATE hplj1020_build_options hplj1020_core)
  add_test(NAME hplj1020-pappl-service-contracts COMMAND hplj1020-pappl-service-contracts)
  add_executable(hplj1020-pappl-log-rotation-contract
    tests/pappl_log_rotation_contract.c)
  target_include_directories(hplj1020-pappl-log-rotation-contract PRIVATE
    "${HPLJ1020_PAPPL_PREFIX}/include")
  target_link_libraries(hplj1020-pappl-log-rotation-contract PRIVATE
    hplj1020_build_options hplj1020_pappl)
  add_test(NAME hplj1020-pappl-log-rotation-contract
    COMMAND hplj1020-pappl-log-rotation-contract)
  add_executable(hplj1020-make-test-raster tests/make_test_raster.m)
  target_link_libraries(hplj1020-make-test-raster PRIVATE
    hplj1020_build_options ${HPLJ1020_CUPS_LIBRARY}
    ${HPLJ1020_APPKIT_FRAMEWORK})
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  # Compile the same runtime on a test-only port; never bind the installed
  # provider's port while validating an installation candidate.
  add_executable(hplj1020-test-service
    src/main.c src/pappl_runtime.c src/pappl.c)
  target_compile_definitions(hplj1020-test-service PRIVATE HPLJ_TEST_SERVICE=1)
  target_include_directories(hplj1020-test-service PRIVATE
    "${HPLJ1020_PAPPL_PREFIX}/include")
  target_link_libraries(hplj1020-test-service PRIVATE
    hplj1020_build_options hplj1020_pappl)
  add_test(NAME hplj1020-pappl-integration
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pappl_integration.py
      $<TARGET_FILE:hplj1020-test-service> $<TARGET_FILE:hplj1020-make-test-raster>
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/invalid-resolution.test
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/invalid-quality.test
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/malformed-raster.test
      ${CMAKE_CURRENT_SOURCE_DIR}/validation/golden-corpus
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/submit-raster.test)
  set_tests_properties(hplj1020-pappl-integration PROPERTIES
    SKIP_RETURN_CODE 77 TIMEOUT 90)
  add_test(NAME hplj1020-media-integration
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_media_integration.py
      $<TARGET_FILE:hplj1020-test-service> $<TARGET_FILE:hplj1020-make-test-raster>)
  set_tests_properties(hplj1020-media-integration PROPERTIES TIMEOUT 60)
  add_test(NAME hplj1020-queue-reconciliation
    COMMAND ${Python3_EXECUTABLE} -m unittest tests.test_queue_reconciliation)
  set_tests_properties(hplj1020-queue-reconciliation PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-personal-install
    COMMAND ${Python3_EXECUTABLE} -m unittest tests.test_personal_install)
  set_tests_properties(hplj1020-personal-install PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-personal-update
    COMMAND ${Python3_EXECUTABLE} -B -m unittest tests.test_personal_update)
  set_tests_properties(hplj1020-personal-update PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-firmware-import-cli
    COMMAND ${Python3_EXECUTABLE} -m unittest tests.test_firmware_import_cli)
  set_tests_properties(hplj1020-firmware-import-cli PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-personal-release
    COMMAND ${Python3_EXECUTABLE} -B -m unittest tests.test_personal_release)
  set_tests_properties(hplj1020-personal-release PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME hplj1020-version COMMAND hplj1020 --version)
  set_tests_properties(hplj1020-version PROPERTIES
    PASS_REGULAR_EXPRESSION "hplj1020 ${PROJECT_VERSION}")
endif()

if(BUILD_TESTING)
  add_test(NAME hplj1020-diagnostics
    COMMAND ${Python3_EXECUTABLE} -B -m unittest tests.test_diagnostics)
  set_tests_properties(hplj1020-diagnostics PROPERTIES
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
  add_executable(hplj1020-diagnostics-contracts tests/diagnostics_contracts.c)
  target_link_libraries(hplj1020-diagnostics-contracts PRIVATE
    hplj1020_build_options hplj1020_core Threads::Threads)
  add_test(NAME hplj1020-diagnostics-contracts COMMAND hplj1020-diagnostics-contracts)
endif()
