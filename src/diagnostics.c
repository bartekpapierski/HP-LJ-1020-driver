// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/diagnostics.h"
#include "hplj/pappl.h"
#include "hplj/version.h"

#include <fcntl.h>
#include <limits.h>
#include <string.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

bool hplj_diagnostics_open(struct hplj_diagnostics *diagnostics, const char *path) {
  memset(diagnostics, 0, sizeof(*diagnostics));
  if (pthread_mutex_init(&diagnostics->mutex, NULL) != 0) {
    return false;
  }
  int fd = open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600);
  struct stat info;
  if (fd < 0 || fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) ||
      info.st_uid != geteuid() || info.st_nlink != 1 ||
      (info.st_mode & 0777) != 0600 || ftruncate(fd, 0) != 0) {
    if (fd >= 0) {
      close(fd);
    }
    pthread_mutex_destroy(&diagnostics->mutex);
    return false;
  }
  // Start a fresh privacy boundary on each service start, including upgrades
  // from the old free-form PAPPL log. Never retain rotated copies.
  diagnostics->log = fdopen(fd, "w+");
  if (diagnostics->log == NULL) {
    close(fd);
    pthread_mutex_destroy(&diagnostics->mutex);
    return false;
  }
  if (!hplj_diagnostics_event(diagnostics, time(NULL), NULL)) {
    hplj_diagnostics_close(diagnostics);
    return false;
  }
  return true;
}

void hplj_diagnostics_close(struct hplj_diagnostics *diagnostics) {
  if (diagnostics->log != NULL) {
    fclose(diagnostics->log);
  }
  pthread_mutex_destroy(&diagnostics->mutex);
}

bool hplj_diagnostics_event(struct hplj_diagnostics *diagnostics, time_t now,
                             const struct hplj_job_metadata *job) {
  char record[512];
  int length;
  if (job == NULL) {
    length = snprintf(record, sizeof(record),
                      "{\"schemaVersion\":\"1.0.0\",\"time\":%lld,\"event\":\"service\"}\n",
                      (long long)now);
  } else {
    length = snprintf(record, sizeof(record),
                      "{\"schemaVersion\":\"1.0.0\",\"time\":%lld,\"event\":\"job\","
                      "\"state\":%u,\"error\":%u,\"bytesSent\":%zu,\"pagesCompleted\":%u}\n",
                      (long long)now, (unsigned int)job->state,
                      (unsigned int)job->error.category, job->bytes_sent,
                      job->pages_completed);
  }
  if (length <= 0 || (size_t)length >= sizeof(record) || now < 0) {
    return false;
  }
  pthread_mutex_lock(&diagnostics->mutex);
  bool ok = true;
  if (diagnostics->bytes + (size_t)length > HPLJ_MAX_LOG_BYTES ||
      now < diagnostics->created ||
      now - diagnostics->created >= HPLJ_MAX_LOG_AGE_SECONDS) {
    ok = fflush(diagnostics->log) == 0 &&
         ftruncate(fileno(diagnostics->log), 0) == 0 &&
         fseek(diagnostics->log, 0, SEEK_SET) == 0;
    diagnostics->bytes = 0;
  }
  if (diagnostics->bytes == 0) {
    diagnostics->created = now;
  }
  if (ok) {
    ok = fwrite(record, 1, (size_t)length, diagnostics->log) == (size_t)length &&
         fflush(diagnostics->log) == 0;
    diagnostics->bytes += (size_t)length;
  }
  pthread_mutex_unlock(&diagnostics->mutex);
  return ok;
}

bool hplj_diagnostics_snapshot(const char *state_path, time_t now,
                                enum hplj_device_state device,
                                enum hplj_error_category error,
                                bool firmware_available) {
  char path[PATH_MAX], temporary[PATH_MAX];
  if (snprintf(path, sizeof(path), "%s.diagnostics.json", state_path) >= (int)sizeof(path) ||
      snprintf(temporary, sizeof(temporary), "%s.XXXXXX", path) >= (int)sizeof(temporary)) {
    return false;
  }
  int fd = mkstemp(temporary);
  if (fd < 0) {
    return false;
  }
  FILE *file = fdopen(fd, "w");
  if (file == NULL) {
    close(fd);
    unlink(temporary);
    return false;
  }
  bool ok = fprintf(file,
      "{\"schemaVersion\":\"1.0.0\",\"time\":%lld,"
      "\"productVersion\":\"%s\",\"dependencies\":{\"pappl\":\"%s\","
      "\"libusb\":\"%s\",\"foo2zjs\":\"%s\"},"
      "\"device\":%u,\"error\":%u,\"firmwareAvailable\":%s}\n",
      (long long)now, hplj_product_version(), hplj_dependency_version("pappl"),
      hplj_dependency_version("libusb"), hplj_dependency_version("foo2zjs"),
      (unsigned int)device, (unsigned int)error,
      firmware_available ? "true" : "false") > 0;
  if (fclose(file) != 0) {
    ok = false;
  }
  if (ok) {
    ok = rename(temporary, path) == 0;
  }
  if (!ok) {
    unlink(temporary);
  }
  return ok;
}
