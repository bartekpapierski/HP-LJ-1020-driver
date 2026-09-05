// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/firmware.h"
#include "firmware_test_support.h"

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const unsigned char synthetic_firmware[] = "synthetic firmware fixture";
static const unsigned char synthetic_sha256[HPLJ_SHA256_SIZE] = {
    0xa2, 0xc3, 0xeb, 0x95, 0x1d, 0x83, 0x61, 0xcc, 0x94, 0xd9, 0x42,
    0x43, 0x33, 0xc2, 0x65, 0xa6, 0x4e, 0x5d, 0x17, 0x78, 0xf2, 0x75,
    0x21, 0x02, 0x01, 0xbf, 0x02, 0x01, 0xb9, 0xa9, 0x32, 0x4b};

struct fake_store {
  unsigned int commits;
  unsigned int removals;
  size_t stored_size;
  struct hplj_firmware_metadata metadata;
  enum hplj_error_category commit_error;
  enum hplj_error_category removal_error;
};

static enum hplj_error_category fake_commit(
    void *context, const unsigned char *contents, size_t byte_count,
    const struct hplj_firmware_metadata *metadata) {
  struct fake_store *store = context;
  assert(contents != NULL);
  store->commits++;
  if (store->commit_error != HPLJ_ERROR_NONE) {
    return store->commit_error;
  }
  store->stored_size = byte_count;
  store->metadata = *metadata;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category fake_remove_all(void *context) {
  struct fake_store *store = context;
  store->removals++;
  return store->removal_error;
}

static struct hplj_firmware_allowlist_entry synthetic_allowlist(void) {
  struct hplj_firmware_allowlist_entry entry = {
      .byte_count = sizeof(synthetic_firmware) - 1,
      .version_build = "synthetic-reference-build",
  };
  memcpy(entry.sha256, synthetic_sha256, sizeof(entry.sha256));
  return entry;
}

static struct hplj_firmware_result import_synthetic(
    const struct hplj_firmware_import_request *request,
    const struct hplj_firmware_allowlist_entry *allowed,
    const struct hplj_firmware_store *store) {
  return hplj_firmware_import_synthetic_host_fixture(request, allowed, 1, store);
}

static void test_supported_firmware_is_committed_with_local_metadata(void) {
  struct fake_store stored = {0};
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};
  const struct hplj_firmware_allowlist_entry allowed = synthetic_allowlist();
  struct hplj_firmware_import_request request = {
      .contents = synthetic_firmware,
      .byte_count = sizeof(synthetic_firmware) - 1,
      .source_description = "synthetic user fixture",
      .lawful_acquisition_affirmed = true,
  };

  struct hplj_firmware_result result = import_synthetic(&request, &allowed, &store);

  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(stored.commits == 1);
  assert(stored.stored_size == sizeof(synthetic_firmware) - 1);
  assert(strcmp(stored.metadata.source_description, "synthetic user fixture") == 0);
  assert(strcmp(stored.metadata.version_build, "synthetic-reference-build") == 0);
  assert(strcmp(stored.metadata.sha256,
                "a2c3eb951d8361cc94d9424333c265a64e5d1778f275210201bf0201b9a9324b") == 0);
  assert(stored.metadata.lawful_acquisition_affirmed);
}

static void test_import_requires_affirmation_after_presenting_separate_terms(void) {
  struct fake_store stored = {0};
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};
  const struct hplj_firmware_allowlist_entry allowed = synthetic_allowlist();
  const struct hplj_firmware_import_request request = {
      .contents = synthetic_firmware,
      .byte_count = sizeof(synthetic_firmware) - 1,
      .source_description = "synthetic user fixture",
      .lawful_acquisition_affirmed = false,
  };

  struct hplj_firmware_result result = import_synthetic(&request, &allowed, &store);

  assert(strstr(hplj_firmware_import_disclosure(), "HP owns") != NULL);
  assert(strstr(hplj_firmware_import_disclosure(), "separate terms") != NULL);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED);
  assert(result.error.action == HPLJ_ACTION_AFFIRM_LAWFUL_ACQUISITION);
  assert(stored.commits == 0);
}

static void test_production_import_is_closed_until_reference_evidence_is_accepted(void) {
  struct fake_store stored = {0};
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};
  struct hplj_firmware_import_request request = {
      .contents = synthetic_firmware,
      .byte_count = sizeof(synthetic_firmware) - 1,
      .source_description = "synthetic user fixture",
      .lawful_acquisition_affirmed = true,
  };

  struct hplj_firmware_result result = hplj_firmware_import(&request, &store);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_UNSUPPORTED);
  assert(stored.commits == 0);

  request.lawful_acquisition_affirmed = false;
  result = hplj_firmware_import(&request, &store);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED);

  request.lawful_acquisition_affirmed = true;
  request.contents = NULL;
  request.byte_count = 0;
  request.source_read = HPLJ_FIRMWARE_READ_FAILED;
  result = hplj_firmware_import(&request, &store);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_CORRUPT);
}

static void test_unsupported_and_corrupt_firmware_have_distinct_recovery(void) {
  struct fake_store stored = {0};
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};
  const struct hplj_firmware_allowlist_entry allowed = synthetic_allowlist();
  unsigned char unsupported[sizeof(synthetic_firmware) - 1];
  memset(unsupported, 0x5a, sizeof(unsupported));
  struct hplj_firmware_import_request request = {
      .contents = unsupported,
      .byte_count = sizeof(unsupported),
      .source_description = "unsupported synthetic fixture",
      .lawful_acquisition_affirmed = true,
  };

  struct hplj_firmware_result result = import_synthetic(&request, &allowed, &store);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_UNSUPPORTED);
  assert(result.error.action == HPLJ_ACTION_SELECT_SUPPORTED_FIRMWARE);
  assert(stored.commits == 0);

  request.contents = NULL;
  request.byte_count = 0;
  request.source_read = HPLJ_FIRMWARE_READ_FAILED;
  result = import_synthetic(&request, &allowed, &store);
  assert(result.error.category == HPLJ_ERROR_FIRMWARE_CORRUPT);
  assert(result.error.action == HPLJ_ACTION_REACQUIRE_FIRMWARE);
  assert(stored.commits == 0);
}

static void test_complete_removal_deletes_firmware_and_metadata(void) {
  struct fake_store stored = {0};
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};

  struct hplj_error result = hplj_firmware_remove(&store);

  assert(result.category == HPLJ_ERROR_NONE);
  assert(stored.removals == 1);
}

static void test_storage_and_removal_failures_never_report_success(void) {
  struct fake_store stored = {.commit_error = HPLJ_ERROR_TRANSFER_INCOMPLETE};
  stored.metadata.source_description = "prior valid source";
  stored.metadata.version_build = "prior valid build";
  strcpy(stored.metadata.sha256,
         "0000000000000000000000000000000000000000000000000000000000000000");
  const struct hplj_firmware_store store = {
      .commit = fake_commit, .remove_all = fake_remove_all, .context = &stored};
  const struct hplj_firmware_allowlist_entry allowed = synthetic_allowlist();
  const struct hplj_firmware_import_request request = {
      .contents = synthetic_firmware,
      .byte_count = sizeof(synthetic_firmware) - 1,
      .source_description = "synthetic user fixture",
      .lawful_acquisition_affirmed = true,
  };

  struct hplj_firmware_result imported = import_synthetic(&request, &allowed, &store);
  assert(imported.error.category == HPLJ_ERROR_TRANSFER_INCOMPLETE);
  assert(imported.error.action == HPLJ_ACTION_RETRY_FIRMWARE_IMPORT);
  assert(strcmp(stored.metadata.source_description, "prior valid source") == 0);
  assert(strcmp(stored.metadata.version_build, "prior valid build") == 0);
  assert(strcmp(stored.metadata.sha256,
                "0000000000000000000000000000000000000000000000000000000000000000") == 0);

  stored.removal_error = HPLJ_ERROR_TRANSFER_INCOMPLETE;
  struct hplj_error removed = hplj_firmware_remove(&store);
  assert(removed.category == HPLJ_ERROR_TRANSFER_INCOMPLETE);
  assert(removed.retry == HPLJ_RETRY_EXPLICIT);
  assert(removed.action == HPLJ_ACTION_RETRY_UNINSTALL);
}

static void test_local_store_atomically_persists_private_data_and_removes_it(void) {
  char temporary[] = "/tmp/hplj-firmware-contracts.XXXXXX";
  assert(mkdtemp(temporary) != NULL);
  char directory[1024];
  assert(snprintf(directory, sizeof(directory), "%s/private", temporary) > 0);
  struct hplj_firmware_local_store local = {.directory = directory};
  struct hplj_firmware_store store;
  hplj_firmware_local_store_init(&store, &local);
  const struct hplj_firmware_allowlist_entry allowed = synthetic_allowlist();
  const struct hplj_firmware_import_request request = {
      .contents = synthetic_firmware,
      .byte_count = sizeof(synthetic_firmware) - 1,
      .source_description = "synthetic user fixture",
      .lawful_acquisition_affirmed = true,
  };

  struct hplj_firmware_result imported = import_synthetic(&request, &allowed, &store);
  assert(imported.error.category == HPLJ_ERROR_NONE);

  char stored_firmware[1024];
  char stored_metadata[1024];
  assert(snprintf(stored_firmware, sizeof(stored_firmware), "%s/active/contents", directory) > 0);
  assert(snprintf(stored_metadata, sizeof(stored_metadata), "%s/active/metadata", directory) > 0);
  struct stat status;
  assert(stat(stored_firmware, &status) == 0);
  assert((status.st_mode & 0777) == 0600);
  assert((size_t)status.st_size == sizeof(synthetic_firmware) - 1);
  assert(stat(stored_metadata, &status) == 0);
  assert((status.st_mode & 0777) == 0600);

  struct hplj_firmware_import_request replacement = request;
  replacement.source_description = "replacement synthetic source";
  assert(chmod(directory, 0500) == 0);
  assert(import_synthetic(&replacement, &allowed, &store).error.category ==
         HPLJ_ERROR_FIRMWARE_STORAGE_FAILED);
  FILE *metadata_file = fopen(stored_metadata, "r");
  assert(metadata_file != NULL);
  char metadata_contents[512];
  size_t metadata_length = fread(metadata_contents, 1, sizeof(metadata_contents) - 1,
                                 metadata_file);
  metadata_contents[metadata_length] = '\0';
  assert(fclose(metadata_file) == 0);
  assert(strstr(metadata_contents, "source=synthetic user fixture\n") != NULL);

  assert(chmod(directory, 0700) == 0);
  assert(import_synthetic(&replacement, &allowed, &store).error.category ==
         HPLJ_ERROR_NONE);
  metadata_file = fopen(stored_metadata, "r");
  assert(metadata_file != NULL);
  metadata_length = fread(metadata_contents, 1, sizeof(metadata_contents) - 1, metadata_file);
  metadata_contents[metadata_length] = '\0';
  assert(fclose(metadata_file) == 0);
  assert(strstr(metadata_contents, "source=replacement synthetic source\n") != NULL);

  assert(hplj_firmware_remove(&store).category == HPLJ_ERROR_NONE);
  assert(access(directory, F_OK) != 0);
  assert(rmdir(temporary) == 0);
}

int main(void) {
  test_supported_firmware_is_committed_with_local_metadata();
  test_import_requires_affirmation_after_presenting_separate_terms();
  test_production_import_is_closed_until_reference_evidence_is_accepted();
  test_unsupported_and_corrupt_firmware_have_distinct_recovery();
  test_complete_removal_deletes_firmware_and_metadata();
  test_storage_and_removal_failures_never_report_success();
  test_local_store_atomically_persists_private_data_and_removes_it();
  return 0;
}
