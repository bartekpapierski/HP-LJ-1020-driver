// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_FIRMWARE_H
#define HPLJ_FIRMWARE_H

#include "hplj/error.h"

#include <stdbool.h>
#include <stddef.h>

#define HPLJ_SHA256_SIZE 32
#define HPLJ_SHA256_HEX_SIZE 65

struct hplj_firmware_allowlist_entry {
  unsigned char sha256[HPLJ_SHA256_SIZE];
  size_t byte_count;
  const char *version_build;
};

enum hplj_firmware_source_read {
  HPLJ_FIRMWARE_READ_COMPLETE,
  HPLJ_FIRMWARE_READ_FAILED,
};

struct hplj_firmware_import_request {
  const unsigned char *contents;
  size_t byte_count;
  const char *source_description;
  bool lawful_acquisition_affirmed;
  enum hplj_firmware_source_read source_read;
};

struct hplj_firmware_metadata {
  const char *source_description;
  const char *version_build;
  char sha256[HPLJ_SHA256_HEX_SIZE];
  bool lawful_acquisition_affirmed;
};

struct hplj_firmware_store {
  /*
   * commit must atomically replace both the private file and its metadata.
   * It must copy all borrowed data before returning.
   */
  enum hplj_error_category (*commit)(void *context, const unsigned char *contents,
                                     size_t byte_count,
                                     const struct hplj_firmware_metadata *metadata);
  /* remove_all must remove both the private file and its metadata. */
  enum hplj_error_category (*remove_all)(void *context);
  void *context;
};

struct hplj_firmware_local_store {
  const char *directory;
};

struct hplj_firmware_result {
  struct hplj_error error;
  struct hplj_firmware_metadata metadata;
};

const char *hplj_firmware_import_disclosure(void);
struct hplj_firmware_result hplj_firmware_import(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_store *store);
struct hplj_error hplj_firmware_remove(const struct hplj_firmware_store *store);
void hplj_firmware_local_store_init(struct hplj_firmware_store *store,
                                    struct hplj_firmware_local_store *local);

#endif
