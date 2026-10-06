// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/firmware.h"
#include "hplj/pappl.h"
#include "hplj/version.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HPLJ_MAX_FIRMWARE_INPUT (1024 * 1024)

static const char *option_value(int argc, char *argv[], const char *name) {
  for (int index = 2; index + 1 < argc; index++) {
    if (strcmp(argv[index], name) == 0) {
      return argv[index + 1];
    }
  }
  return NULL;
}

static int serve(int argc, char *argv[]) {
  struct hplj_service_config config = {
      .queue_name = HPLJ_QUEUE_NAME,
      .loopback_host = HPLJ_IPV4_LOOPBACK,
      .ipp_port = HPLJ_IPP_PORT,
      .paths = {
          .firmware_path = option_value(argc, argv, "--firmware"),
          .state_path = option_value(argc, argv, "--state"),
          .spool_path = option_value(argc, argv, "--spool"),
          .log_path = option_value(argc, argv, "--log"),
          .socket_path = option_value(argc, argv, "--socket"),
      },
      .device_uri = option_value(argc, argv, "--device-uri"),
  };
  if (config.paths.state_path == NULL || config.paths.spool_path == NULL ||
      config.paths.log_path == NULL || config.paths.socket_path == NULL ||
      config.device_uri == NULL) {
    fputs("usage: hplj1020 --serve --state PATH --spool PATH --log PATH "
          "--socket PATH --device-uri URI [--firmware PATH]\n",
          stderr);
    return 2;
  }
  return hplj_pappl_serve(&config);
}

static int import_firmware(int argc, char *argv[]) {
  fprintf(stderr, "%s\n", hplj_firmware_import_disclosure());
  if (argc != 7 || strcmp(argv[2], "--firmware") != 0 ||
      strcmp(argv[4], "--source") != 0 ||
      strcmp(argv[6], "--affirm-lawful-acquisition") != 0) {
    fputs("usage: hplj1020 --import-firmware --firmware PRIVATE_DIRECTORY "
          "--source DESCRIPTION --affirm-lawful-acquisition < FIRMWARE\n",
          stderr);
    return 2;
  }
  unsigned char *contents = malloc(HPLJ_MAX_FIRMWARE_INPUT + 1);
  if (contents == NULL) {
    fputs("firmware import failed: allocation error\n", stderr);
    return 1;
  }
  size_t byte_count = fread(contents, 1, HPLJ_MAX_FIRMWARE_INPUT + 1, stdin);
  if (ferror(stdin) || byte_count == 0 || byte_count > HPLJ_MAX_FIRMWARE_INPUT) {
    free(contents);
    fputs("firmware import failed: missing, oversized, or unreadable input\n",
          stderr);
    return 1;
  }
  struct hplj_firmware_local_store local = {.directory = argv[3]};
  struct hplj_firmware_store store;
  hplj_firmware_local_store_init(&store, &local);
  const struct hplj_firmware_import_request request = {
      .contents = contents,
      .byte_count = byte_count,
      .source_description = argv[5],
      .lawful_acquisition_affirmed = true,
      .source_read = HPLJ_FIRMWARE_READ_COMPLETE,
  };
  struct hplj_firmware_result result = hplj_firmware_import(&request, &store);
  free(contents);
  if (result.error.category != HPLJ_ERROR_NONE) {
    fprintf(stderr, "firmware import failed: %s\n",
            hplj_error_category_name(result.error.category));
    return 1;
  }
  puts("firmware imported into private local storage");
  return 0;
}

int main(int argc, char *argv[]) {
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    printf("hplj1020 %s\n", hplj_product_version());
    printf("pappl %s\n", hplj_dependency_version("pappl"));
    printf("libusb %s\n", hplj_dependency_version("libusb"));
    printf("foo2zjs %s\n", hplj_dependency_version("foo2zjs"));
    return 0;
  }
  if (argc >= 2 && strcmp(argv[1], "--serve") == 0) {
    return serve(argc, argv);
  }
  if (argc >= 2 && strcmp(argv[1], "--import-firmware") == 0) {
    return import_firmware(argc, argv);
  }
  puts("HP LaserJet 1020 macOS printing solution");
  return 0;
}
