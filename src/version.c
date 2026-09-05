// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/version.h"

#include <string.h>

const char *hplj_product_version(void) {
  return "0.1.0";
}

const char *hplj_dependency_version(const char *name) {
  if (strcmp(name, "pappl") == 0) {
    return "1.4.12";
  }
  if (strcmp(name, "libusb") == 0) {
    return "1.0.30";
  }
  if (strcmp(name, "foo2zjs") == 0) {
    return "80499ed5bf6caa2963ad337e37cfda78a80aab1e";
  }
  return NULL;
}
