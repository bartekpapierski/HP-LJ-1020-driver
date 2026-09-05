// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/version.h"

#include <stdio.h>
#include <string.h>

int main(int argc, char *argv[]) {
  if (argc == 2 && strcmp(argv[1], "--version") == 0) {
    printf("hplj1020 %s\n", hplj_product_version());
    printf("pappl %s\n", hplj_dependency_version("pappl"));
    printf("libusb %s\n", hplj_dependency_version("libusb"));
    printf("foo2zjs %s\n", hplj_dependency_version("foo2zjs"));
    return 0;
  }
  puts("HP LaserJet 1020 macOS printing solution");
  return 0;
}
