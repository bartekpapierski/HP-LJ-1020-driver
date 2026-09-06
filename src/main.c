// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"
#include "hplj/version.h"

#include <stdio.h>
#include <string.h>

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
  puts("HP LaserJet 1020 macOS printing solution");
  return 0;
}
