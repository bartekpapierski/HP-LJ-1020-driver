// SPDX-License-Identifier: GPL-2.0-or-later
#include <pappl/pappl.h>

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

int main(void) {
  char root[] = "/tmp/hplj1020-log-rotation.XXXXXX";
  assert(mkdtemp(root) != NULL);

  char spool[PATH_MAX];
  char log_path[PATH_MAX];
  char backup_path[PATH_MAX];
  assert(snprintf(spool, sizeof(spool), "%s/spool", root) <
         (int)sizeof(spool));
  assert(snprintf(log_path, sizeof(log_path), "%s/service.log", root) <
         (int)sizeof(log_path));
  assert(snprintf(backup_path, sizeof(backup_path), "%s.O", log_path) <
         (int)sizeof(backup_path));
  assert(mkdir(spool, 0700) == 0);

  pappl_system_t *system = papplSystemCreate(
      PAPPL_SOPTIONS_NO_TLS, "log-rotation-contract", 0, NULL, spool,
      log_path, PAPPL_LOGLEVEL_INFO, NULL, false);
  assert(system != NULL);
  papplLog(system, PAPPL_LOGLEVEL_INFO, "retention-contract-marker");

  struct stat log_status;
  assert(stat(log_path, &log_status) == 0);
#if defined(__APPLE__)
  const time_t created_at = log_status.st_birthtimespec.tv_sec;
#else
  const time_t created_at = log_status.st_mtime;
#endif
  assert(!papplSystemRotateLog(system, created_at - 1));
  assert(access(backup_path, F_OK) != 0);
  assert(papplSystemRotateLog(system, created_at));
  assert(access(backup_path, F_OK) == 0);

  papplSystemDelete(system);
  assert(unlink(log_path) == 0);
  assert(unlink(backup_path) == 0);
  assert(rmdir(spool) == 0);
  assert(rmdir(root) == 0);
  return 0;
}
