// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/diagnostics.h"
#include "hplj/pappl.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(void) {
  char path[] = "/tmp/hplj-diagnostics-XXXXXX";
  int fd = mkstemp(path);
  assert(fd >= 0);
  close(fd);
  struct hplj_diagnostics diagnostics;
  assert(hplj_diagnostics_open(&diagnostics, path));
  struct hplj_job_metadata job = {.state = HPLJ_JOB_COMPLETED,
      .error = {.detail = "PRIVATE document username credential firmware"}};
  time_t now = diagnostics.created;
  assert(hplj_diagnostics_event(&diagnostics, now, &job));
  for (int i = 0; i < 120000; i++) {
    assert(hplj_diagnostics_event(&diagnostics, now, &job));
  }
  struct stat info;
  assert(stat(path, &info) == 0 && info.st_size <= HPLJ_MAX_LOG_BYTES);
  assert((info.st_mode & 0777) == 0600);
  assert(hplj_diagnostics_event(&diagnostics,
      now + HPLJ_MAX_LOG_AGE_SECONDS, NULL));
  assert(stat(path, &info) == 0 && info.st_size < 512);
  rewind(diagnostics.log);
  char line[512];
  assert(fgets(line, sizeof(line), diagnostics.log) != NULL);
  assert(strstr(line, "PRIVATE") == NULL);
  assert(strstr(line, "\"event\":\"service\"") != NULL);
  hplj_diagnostics_close(&diagnostics);
  assert(hplj_diagnostics_snapshot(path, now, HPLJ_DEVICE_READY,
                                    HPLJ_ERROR_NONE, true));
  char snapshot[256];
  snprintf(snapshot, sizeof(snapshot), "%s.diagnostics.json", path);
  assert(stat(snapshot, &info) == 0 && (info.st_mode & 0777) == 0600);
  unlink(snapshot);
  unlink(path);
  assert(symlink("/dev/null", path) == 0);
  assert(!hplj_diagnostics_open(&diagnostics, path));
  unlink(path);
  return 0;
}
