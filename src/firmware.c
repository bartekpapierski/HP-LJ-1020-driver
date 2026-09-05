// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/firmware.h"

#include <CommonCrypto/CommonDigest.h>
#include <limits.h>
#include <string.h>

static bool hplj_metadata_text_is_valid(const char *text, size_t maximum_length) {
  if (text == NULL) {
    return false;
  }
  size_t length = strlen(text);
  if (length == 0 || length > maximum_length) {
    return false;
  }
  for (size_t index = 0; index < length; index++) {
    unsigned char character = (unsigned char)text[index];
    if (character < 0x20 || character == 0x7f) {
      return false;
    }
  }
  return true;
}

static struct hplj_firmware_result hplj_firmware_failure(
    enum hplj_error_category category, enum hplj_human_action action, const char *detail) {
  return (struct hplj_firmware_result){
      .error = hplj_error_make(category, HPLJ_RETRY_NEVER, action, detail),
  };
}

static void hplj_sha256_hex(const unsigned char digest[HPLJ_SHA256_SIZE],
                            char output[HPLJ_SHA256_HEX_SIZE]) {
  static const char hexadecimal[] = "0123456789abcdef";
  for (size_t index = 0; index < HPLJ_SHA256_SIZE; index++) {
    output[index * 2] = hexadecimal[digest[index] >> 4];
    output[index * 2 + 1] = hexadecimal[digest[index] & 0x0f];
  }
  output[HPLJ_SHA256_HEX_SIZE - 1] = '\0';
}

const char *hplj_firmware_import_disclosure(void) {
  return "HP owns the required firmware and licenses it under separate terms. "
         "Import requires your affirmation that you lawfully acquired the supported file "
         "and accept its applicable terms. Import grants no redistribution rights; the file "
         "and its metadata remain private on this Mac and complete uninstall removes both.";
}

static struct hplj_firmware_result hplj_firmware_validate_request(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_store *store) {
  if (request == NULL) {
    return hplj_firmware_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_ACTION_NONE,
                                 "invalid firmware import request");
  }
  if (request->source_read != HPLJ_FIRMWARE_READ_COMPLETE &&
      request->source_read != HPLJ_FIRMWARE_READ_FAILED) {
    return hplj_firmware_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_ACTION_NONE,
                                 "invalid firmware source read state");
  }
  if (request->source_read == HPLJ_FIRMWARE_READ_FAILED || request->contents == NULL ||
      request->byte_count == 0 || request->byte_count > UINT_MAX) {
    return hplj_firmware_failure(HPLJ_ERROR_FIRMWARE_CORRUPT,
                                 HPLJ_ACTION_REACQUIRE_FIRMWARE,
                                 "user-supplied firmware could not be read completely");
  }
  if (!hplj_metadata_text_is_valid(request->source_description, 4096) || store == NULL ||
      store->commit == NULL) {
    return hplj_firmware_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_ACTION_NONE,
                                 "invalid firmware import request");
  }
  if (!request->lawful_acquisition_affirmed) {
    return hplj_firmware_failure(HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED,
                                 HPLJ_ACTION_AFFIRM_LAWFUL_ACQUISITION,
                                 "lawful acquisition and applicable terms were not affirmed");
  }
  return (struct hplj_firmware_result){
      .error = hplj_error_make(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                               HPLJ_ACTION_NONE, "firmware import request validated"),
  };
}

static struct hplj_firmware_result hplj_firmware_import_with_policy(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_allowlist_entry *allowlist, size_t allowlist_count,
    const struct hplj_firmware_store *store) {
  struct hplj_firmware_result validation = hplj_firmware_validate_request(request, store);
  if (validation.error.category != HPLJ_ERROR_NONE) {
    return validation;
  }
  if (allowlist == NULL || allowlist_count == 0) {
    return hplj_firmware_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_ACTION_NONE,
                                 "invalid firmware allow-list");
  }

  unsigned char digest[HPLJ_SHA256_SIZE];
  CC_SHA256(request->contents, (CC_LONG)request->byte_count, digest);
  const struct hplj_firmware_allowlist_entry *matched = NULL;
  for (size_t index = 0; index < allowlist_count; index++) {
    if (allowlist[index].byte_count == request->byte_count &&
        memcmp(allowlist[index].sha256, digest, sizeof(digest)) == 0) {
      matched = &allowlist[index];
      break;
    }
  }
  if (matched == NULL) {
    return hplj_firmware_failure(HPLJ_ERROR_FIRMWARE_UNSUPPORTED,
                                 HPLJ_ACTION_SELECT_SUPPORTED_FIRMWARE,
                                 "user-supplied firmware is not allow-listed");
  }
  if (!hplj_metadata_text_is_valid(matched->version_build, 256)) {
    return hplj_firmware_failure(HPLJ_ERROR_INVALID_STATE, HPLJ_ACTION_NONE,
                                 "allow-listed firmware has no version/build identifier");
  }

  struct hplj_firmware_metadata metadata = {
      .source_description = request->source_description,
      .version_build = matched->version_build,
      .lawful_acquisition_affirmed = request->lawful_acquisition_affirmed,
  };
  hplj_sha256_hex(digest, metadata.sha256);
  enum hplj_error_category category =
      store->commit(store->context, request->contents, request->byte_count, &metadata);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_firmware_failure(category, HPLJ_ACTION_RETRY_FIRMWARE_IMPORT,
                                 "private local firmware commit failed");
  }
  return (struct hplj_firmware_result){
      .error = hplj_error_make(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                               HPLJ_ACTION_NONE, "firmware imported"),
      .metadata = metadata,
  };
}

struct hplj_firmware_result hplj_firmware_import(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_store *store) {
  struct hplj_firmware_result validation = hplj_firmware_validate_request(request, store);
  if (validation.error.category != HPLJ_ERROR_NONE) {
    return validation;
  }
  return hplj_firmware_failure(
      HPLJ_ERROR_FIRMWARE_UNSUPPORTED, HPLJ_ACTION_SELECT_SUPPORTED_FIRMWARE,
      "no production firmware is allow-listed without accepted reference-printer evidence");
}

struct hplj_firmware_result hplj_firmware_import_synthetic_host_fixture(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_allowlist_entry *allowlist, size_t allowlist_count,
    const struct hplj_firmware_store *store) {
  return hplj_firmware_import_with_policy(request, allowlist, allowlist_count, store);
}

struct hplj_error hplj_firmware_remove(const struct hplj_firmware_store *store) {
  if (store == NULL || store->remove_all == NULL) {
    return hplj_error_make(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                           "invalid firmware removal request");
  }
  enum hplj_error_category category = store->remove_all(store->context);
  if (category != HPLJ_ERROR_NONE) {
    return hplj_error_make(category, HPLJ_RETRY_EXPLICIT, HPLJ_ACTION_RETRY_UNINSTALL,
                           "firmware or metadata remains after removal");
  }
  return hplj_error_make(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC, HPLJ_ACTION_NONE,
                         "firmware and metadata removed");
}
