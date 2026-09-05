// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/firmware.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/stdio.h>
#include <unistd.h>

static bool hplj_path(char output[PATH_MAX], const char *directory, const char *name) {
  int length = snprintf(output, PATH_MAX, "%s/%s", directory, name);
  return length > 0 && length < PATH_MAX;
}

static enum hplj_error_category hplj_write_private(const char *path,
                                                    const unsigned char *contents,
                                                    size_t byte_count) {
  int descriptor = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
  if (descriptor < 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  size_t written = 0;
  while (written < byte_count) {
    ssize_t result = write(descriptor, contents + written, byte_count - written);
    if (result <= 0) {
      close(descriptor);
      return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
    }
    written += (size_t)result;
  }
  if (fsync(descriptor) != 0 || close(descriptor) != 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_remove_generation(const char *directory) {
  char contents[PATH_MAX];
  char metadata[PATH_MAX];
  if (!hplj_path(contents, directory, "contents") ||
      !hplj_path(metadata, directory, "metadata")) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  if ((unlink(contents) != 0 && errno != ENOENT) ||
      (unlink(metadata) != 0 && errno != ENOENT) || rmdir(directory) != 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_sync_directory(const char *directory) {
  int descriptor = open(directory, O_RDONLY);
  if (descriptor < 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  if (fsync(descriptor) != 0 || close(descriptor) != 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_local_commit(
    void *context, const unsigned char *contents, size_t byte_count,
    const struct hplj_firmware_metadata *metadata) {
  struct hplj_firmware_local_store *local = context;
  if (local == NULL || local->directory == NULL || local->directory[0] == '\0') {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  if (mkdir(local->directory, 0700) != 0 && errno != EEXIST) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  struct stat root_status;
  if (lstat(local->directory, &root_status) != 0 || !S_ISDIR(root_status.st_mode) ||
      (root_status.st_mode & 0077) != 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }

  char staging[PATH_MAX];
  if (!hplj_path(staging, local->directory, ".import.XXXXXX") ||
      mkdtemp(staging) == NULL) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  char contents_path[PATH_MAX];
  char metadata_path[PATH_MAX];
  if (!hplj_path(contents_path, staging, "contents") ||
      !hplj_path(metadata_path, staging, "metadata")) {
    hplj_remove_generation(staging);
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }

  size_t metadata_size = strlen(metadata->source_description) +
                         strlen(metadata->version_build) + strlen(metadata->sha256) + 96;
  char *metadata_bytes = malloc(metadata_size);
  if (metadata_bytes == NULL) {
    hplj_remove_generation(staging);
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  int metadata_length = snprintf(
      metadata_bytes, metadata_size,
      "schema=1\naffirmation=lawful-acquisition\nsource=%s\nversion-build=%s\nsha256=%s\n",
      metadata->source_description, metadata->version_build, metadata->sha256);
  enum hplj_error_category result = HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  bool active_created = false;
  bool active_swapped = false;
  char active[PATH_MAX];
  if (metadata_length > 0 && (size_t)metadata_length < metadata_size &&
      hplj_write_private(contents_path, contents, byte_count) == HPLJ_ERROR_NONE &&
      hplj_write_private(metadata_path, (const unsigned char *)metadata_bytes,
                         (size_t)metadata_length) == HPLJ_ERROR_NONE) {
    if (hplj_sync_directory(staging) == HPLJ_ERROR_NONE) {
      if (hplj_path(active, local->directory, "active")) {
        struct stat active_status;
        int active_result = lstat(active, &active_status);
        if (active_result != 0 && errno == ENOENT) {
          if (rename(staging, active) == 0) {
            active_created = true;
            result = HPLJ_ERROR_NONE;
          }
        } else if (active_result == 0 && S_ISDIR(active_status.st_mode) &&
                   renamex_np(staging, active, RENAME_SWAP) == 0) {
          active_swapped = true;
          result = HPLJ_ERROR_NONE;
        }
      }
    }
  }
  free(metadata_bytes);
  if (result != HPLJ_ERROR_NONE) {
    hplj_remove_generation(staging);
  } else if (hplj_sync_directory(local->directory) != HPLJ_ERROR_NONE) {
    if (active_swapped && renamex_np(staging, active, RENAME_SWAP) == 0) {
      hplj_remove_generation(staging);
    } else if (active_created) {
      hplj_remove_generation(active);
    }
    result = HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  } else if (active_swapped) {
    /* The new pair is committed; stale private data is removed best-effort. */
    hplj_remove_generation(staging);
  }
  return result;
}

static enum hplj_error_category hplj_local_remove_all(void *context) {
  struct hplj_firmware_local_store *local = context;
  if (local == NULL || local->directory == NULL) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  DIR *directory = opendir(local->directory);
  if (directory == NULL) {
    return errno == ENOENT ? HPLJ_ERROR_NONE : HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  enum hplj_error_category result = HPLJ_ERROR_NONE;
  const struct dirent *entry;
  while ((entry = readdir(directory)) != NULL) {
    if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
      continue;
    }
    if (strcmp(entry->d_name, "active") != 0 && strncmp(entry->d_name, ".import.", 8) != 0) {
      result = HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
      continue;
    }
    char generation[PATH_MAX];
    if (!hplj_path(generation, local->directory, entry->d_name) ||
        hplj_remove_generation(generation) != HPLJ_ERROR_NONE) {
      result = HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
    }
  }
  if (closedir(directory) != 0 || result != HPLJ_ERROR_NONE ||
      rmdir(local->directory) != 0) {
    return HPLJ_ERROR_FIRMWARE_STORAGE_FAILED;
  }
  return HPLJ_ERROR_NONE;
}

void hplj_firmware_local_store_init(struct hplj_firmware_store *store,
                                    struct hplj_firmware_local_store *local) {
  *store = (struct hplj_firmware_store){
      .commit = hplj_local_commit,
      .remove_all = hplj_local_remove_all,
      .context = local,
  };
}
