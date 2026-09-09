// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"
#include "hplj/firmware.h"
#include "hplj/job.h"
#include "hplj/usb_libusb.h"

#include <pappl/pappl.h>

#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#if CUPS_VERSION_MAJOR < 3
#define cups_page_header_t cups_page_header2_t
#endif

struct hplj_pappl_backend {
  pappl_system_t *system;
  struct hplj_libusb_transport *usb;
  struct hplj_device device;
  unsigned char *firmware;
  size_t firmware_size;
  char firmware_version[HPLJ_FIRMWARE_VERSION_SIZE];
  const char *firmware_path;
  struct hplj_retention_policy retention;
  pappl_printer_t *printer;
  atomic_int device_error;
  pthread_mutex_t device_mutex;
  atomic_bool stopping;
  atomic_bool test_write_delayed;
  atomic_bool test_write_in_progress;
  bool owns_device;
  bool test_device;
  bool test_firmware_uploaded;
  int test_output;
  int test_trace;
  char test_output_path[PATH_MAX];
  char test_trace_path[PATH_MAX];
  char test_conditions_path[PATH_MAX];
};

struct hplj_queue_lookup {
  const char *name;
  pappl_printer_t *printer;
};

struct hplj_active_jobs {
  int *ids;
  size_t count;
  size_t capacity;
};

struct hplj_pappl_job_data {
  unsigned char *page_bits;
  size_t page_size;
  unsigned int rows_received;
  struct hplj_device transport;
  struct hplj_job lifecycle;
  pappl_device_t *pappl_device;
};

#define HPLJ_MAX_FIRMWARE_BYTES (1024U * 1024U)

static bool hplj_read_file(const char *path, unsigned char **contents,
                           size_t *size) {
  int descriptor = open(path, O_RDONLY | O_NOFOLLOW);
  struct stat status;
  if (descriptor < 0 || fstat(descriptor, &status) != 0 ||
      !S_ISREG(status.st_mode) || status.st_size <= 0 ||
      status.st_uid != geteuid() || (status.st_mode & 0777) != 0600 ||
      status.st_nlink != 1 ||
      (uintmax_t)status.st_size > HPLJ_MAX_FIRMWARE_BYTES) {
    if (descriptor >= 0) {
      close(descriptor);
    }
    return false;
  }
  unsigned char *buffer = malloc((size_t)status.st_size + 1);
  if (buffer == NULL) {
    close(descriptor);
    return false;
  }
  size_t offset = 0;
  while (offset < (size_t)status.st_size) {
    ssize_t bytes = read(descriptor, buffer + offset,
                         (size_t)status.st_size - offset);
    if (bytes <= 0) {
      free(buffer);
      close(descriptor);
      return false;
    }
    offset += (size_t)bytes;
  }
  buffer[offset] = '\0';
  if (close(descriptor) != 0) {
    free(buffer);
    return false;
  }
  *contents = buffer;
  *size = offset;
  return true;
}

static bool hplj_private_directory(const char *path) {
  struct stat status;
  return lstat(path, &status) == 0 && S_ISDIR(status.st_mode) &&
         status.st_uid == geteuid() && (status.st_mode & 0077) == 0;
}

static bool hplj_metadata_value(const unsigned char *metadata,
                                size_t metadata_size, const char *name,
                                char *value, size_t value_size) {
  if (metadata == NULL || strlen((const char *)metadata) != metadata_size) {
    return false;
  }
  size_t name_length = strlen(name);
  const char *cursor = (const char *)metadata;
  const char *matched = NULL;
  while (*cursor != '\0') {
    const char *line_end = strchr(cursor, '\n');
    if (line_end == NULL) {
      return false;
    }
    if ((size_t)(line_end - cursor) > name_length + 1 &&
        memcmp(cursor, name, name_length) == 0 && cursor[name_length] == '=') {
      if (matched != NULL) {
        return false;
      }
      matched = cursor + name_length + 1;
      size_t length = (size_t)(line_end - matched);
      if (length == 0 || length >= value_size) {
        return false;
      }
      memcpy(value, matched, length);
      value[length] = '\0';
    }
    cursor = line_end + 1;
  }
  return matched != NULL;
}

static bool hplj_load_firmware(struct hplj_pappl_backend *backend) {
  if (backend->firmware != NULL || backend->firmware_path == NULL) {
    return backend->firmware != NULL;
  }
  char contents_path[PATH_MAX];
  char metadata_path[PATH_MAX];
  char active_path[PATH_MAX];
  if (snprintf(contents_path, sizeof(contents_path), "%s/active/contents",
               backend->firmware_path) >= (int)sizeof(contents_path) ||
      snprintf(metadata_path, sizeof(metadata_path), "%s/active/metadata",
               backend->firmware_path) >= (int)sizeof(metadata_path) ||
      snprintf(active_path, sizeof(active_path), "%s/active",
               backend->firmware_path) >= (int)sizeof(active_path) ||
      !hplj_private_directory(backend->firmware_path) ||
      !hplj_private_directory(active_path)) {
    return false;
  }
  unsigned char *metadata = NULL;
  size_t metadata_size = 0;
  if (!hplj_read_file(contents_path, &backend->firmware,
                      &backend->firmware_size) ||
      !hplj_read_file(metadata_path, &metadata, &metadata_size)) {
    free(backend->firmware);
    backend->firmware = NULL;
    backend->firmware_size = 0;
    free(metadata);
    return false;
  }
  char schema[8];
  char affirmation[64];
  char sha256[HPLJ_SHA256_HEX_SIZE];
  bool metadata_valid =
      hplj_metadata_value(metadata, metadata_size, "schema", schema,
                          sizeof(schema)) &&
      strcmp(schema, "1") == 0 &&
      hplj_metadata_value(metadata, metadata_size, "affirmation", affirmation,
                          sizeof(affirmation)) &&
      strcmp(affirmation, "lawful-acquisition") == 0 &&
      hplj_metadata_value(metadata, metadata_size, "version-build",
                          backend->firmware_version,
                          sizeof(backend->firmware_version)) &&
      hplj_metadata_value(metadata, metadata_size, "sha256", sha256,
                          sizeof(sha256)) &&
      hplj_firmware_digest_matches(backend->firmware, backend->firmware_size,
                                   sha256) &&
      (backend->test_device || hplj_firmware_is_production_allowlisted(
                                   backend->firmware, backend->firmware_size,
                                   backend->firmware_version));
  free(metadata);
  if (!metadata_valid) {
    free(backend->firmware);
    backend->firmware = NULL;
    backend->firmware_size = 0;
    return false;
  }
  return true;
}

static bool hplj_backend_prepare_device_unlocked(
    struct hplj_pappl_backend *backend) {
  if (!backend->owns_device) {
    return true;
  }
  bool firmware_available = hplj_load_firmware(backend);
  if (backend->device.state == HPLJ_DEVICE_READY) {
    const char *expected = firmware_available
                               ? backend->firmware_version
                               : backend->device.firmware_version;
    struct hplj_device_result refreshed =
        hplj_device_revalidate(&backend->device, expected);
    atomic_store(&backend->device_error, refreshed.error.category);
    return refreshed.error.category == HPLJ_ERROR_NONE;
  }
  if (backend->device.state == HPLJ_DEVICE_DISCONNECTED) {
    struct hplj_device_result connected = hplj_device_connect(&backend->device);
    if (connected.error.category != HPLJ_ERROR_NONE) {
      atomic_store(&backend->device_error, connected.error.category);
      return false;
    }
  }
  struct hplj_device_result result = hplj_device_bootstrap_firmware(
      &backend->device,
      firmware_available ? backend->firmware : NULL,
      firmware_available ? backend->firmware_size : 0,
      firmware_available ? backend->firmware_version : "firmware-required");
  atomic_store(&backend->device_error, result.error.category);
  return result.error.category == HPLJ_ERROR_NONE;
}

static bool hplj_backend_prepare_device(struct hplj_pappl_backend *backend) {
  pthread_mutex_lock(&backend->device_mutex);
  bool ready = hplj_backend_prepare_device_unlocked(backend);
  pthread_mutex_unlock(&backend->device_mutex);
  return ready;
}

static void hplj_collect_active_job(pappl_job_t *job, void *data) {
  struct hplj_active_jobs *jobs = data;
  if (jobs->count < jobs->capacity) {
    jobs->ids[jobs->count++] = papplJobGetID(job);
  }
}

static void hplj_update_active_jobs(pappl_printer_t *printer,
                                    const char *message, bool resume) {
  int count = papplPrinterGetNumberOfActiveJobs(printer);
  if (count <= 0) {
    return;
  }
  struct hplj_active_jobs jobs = {
      .ids = calloc((size_t)count, sizeof(*jobs.ids)),
      .capacity = (size_t)count,
  };
  if (jobs.ids == NULL) {
    return;
  }
  papplPrinterIterateActiveJobs(printer, hplj_collect_active_job, &jobs, 1,
                                count);
  for (size_t index = 0; index < jobs.count; index++) {
    pappl_job_t *job = papplPrinterFindJob(printer, jobs.ids[index]);
    if (job == NULL || papplJobIsCanceled(job)) {
      continue;
    }
    if (message != NULL) {
      papplJobSetMessage(job, "%s", message);
    }
    if (resume && papplJobGetState(job) == IPP_JSTATE_STOPPED &&
        (papplJobGetReasons(job) & PAPPL_JREASON_PRINTER_STOPPED) != 0) {
      papplJobResume(job, PAPPL_JREASON_PRINTER_STOPPED);
    }
  }
  free(jobs.ids);
}

static pappl_preason_t hplj_backend_status_reasons(
    struct hplj_pappl_backend *backend, unsigned int *observed_conditions,
    struct hplj_error *observed_error) {
  pthread_mutex_lock(&backend->device_mutex);
  unsigned int conditions = HPLJ_DEVICE_CONDITION_NONE;
  struct hplj_device_result status =
      hplj_device_get_status(&backend->device, &conditions);
  if (status.error.category != HPLJ_ERROR_NONE) {
    atomic_store(&backend->device_error, status.error.category);
    if (observed_error != NULL) {
      *observed_error = status.error;
    }
    pthread_mutex_unlock(&backend->device_mutex);
    return PAPPL_PREASON_OFFLINE;
  }
  if (observed_conditions != NULL) {
    *observed_conditions = conditions;
  }
  if (observed_error != NULL) {
    *observed_error = hplj_error_from_conditions(conditions);
  }
  pappl_preason_t reasons = PAPPL_PREASON_NONE;
  if ((conditions & HPLJ_DEVICE_CONDITION_MEDIA_EMPTY) != 0) {
    reasons |= PAPPL_PREASON_MEDIA_EMPTY | PAPPL_PREASON_MEDIA_NEEDED;
  }
  if ((conditions & HPLJ_DEVICE_CONDITION_NOT_SELECTED) != 0) {
    reasons |= PAPPL_PREASON_OFFLINE;
  }
  if ((conditions & HPLJ_DEVICE_CONDITION_FAULT) != 0) {
    reasons |= PAPPL_PREASON_OTHER;
  }
  if ((conditions & HPLJ_DEVICE_CONDITION_MANUAL_FEED) != 0) {
    reasons |= PAPPL_PREASON_MEDIA_NEEDED;
  }
  if ((conditions & HPLJ_DEVICE_CONDITION_COVER_OPEN) != 0) {
    reasons |= PAPPL_PREASON_COVER_OPEN | PAPPL_PREASON_DOOR_OPEN;
  }
  pthread_mutex_unlock(&backend->device_mutex);
  return reasons;
}

static bool hplj_wait_for_ready(struct hplj_pappl_backend *backend,
                                pappl_job_t *job,
                                struct hplj_job *lifecycle) {
  const struct timespec interval = {.tv_sec = 0, .tv_nsec = 100000000};
  while (!papplJobIsCanceled(job) && !atomic_load(&backend->stopping) &&
         !papplSystemIsShutdown(backend->system)) {
    if (hplj_backend_prepare_device(backend)) {
      unsigned int conditions = HPLJ_DEVICE_CONDITION_NONE;
      struct hplj_error observed_error = {0};
      pappl_preason_t reasons =
          hplj_backend_status_reasons(backend, &conditions, &observed_error);
      papplPrinterSetReasons(backend->printer, reasons,
                             PAPPL_PREASON_DEVICE_STATUS & ~reasons);
      if (reasons == PAPPL_PREASON_NONE) {
        papplPrinterReleaseHeldNewJobs(backend->printer, NULL);
        if (lifecycle != NULL &&
            lifecycle->metadata.state == HPLJ_JOB_WAITING_FOR_MEDIA) {
          (void)hplj_job_resume_media(lifecycle);
        }
        return true;
      }
      papplJobSetMessage(job, "%s", observed_error.detail);
      if (lifecycle != NULL &&
          lifecycle->metadata.state == HPLJ_JOB_PREPARING &&
          (conditions & (HPLJ_DEVICE_CONDITION_MEDIA_EMPTY |
                         HPLJ_DEVICE_CONDITION_MANUAL_FEED |
                         HPLJ_DEVICE_CONDITION_COVER_OPEN)) != 0) {
        (void)hplj_job_wait_for_media(lifecycle, conditions);
      }
    } else {
      bool firmware_required =
          atomic_load(&backend->device_error) == HPLJ_ERROR_FIRMWARE_MISSING;
      papplJobSetMessage(
          job, "%s",
          firmware_required
              ? "firmware-required: import a lawfully acquired, allow-listed firmware file"
              : "held-for-device: reconnect the printer");
    }
    (void)nanosleep(&interval, NULL);
  }
  return false;
}

static bool hplj_monitor_device(pappl_system_t *system, void *data) {
  (void)system;
  struct hplj_pappl_backend *backend = data;
  if (backend->printer == NULL) {
    return true;
  }
  if (hplj_backend_prepare_device(backend)) {
    unsigned int conditions = HPLJ_DEVICE_CONDITION_NONE;
    struct hplj_error observed_error = {0};
    pappl_preason_t reasons =
        hplj_backend_status_reasons(backend, &conditions, &observed_error);
    papplPrinterSetReasons(backend->printer, reasons,
                           PAPPL_PREASON_DEVICE_STATUS & ~reasons);
    if (reasons == PAPPL_PREASON_NONE) {
      papplPrinterReleaseHeldNewJobs(backend->printer, NULL);
      hplj_update_active_jobs(backend->printer, "queued", true);
    } else {
      papplPrinterReleaseHeldNewJobs(backend->printer, NULL);
      hplj_update_active_jobs(backend->printer, observed_error.detail, false);
    }
  } else {
    bool firmware_required =
        atomic_load(&backend->device_error) == HPLJ_ERROR_FIRMWARE_MISSING;
    pappl_preason_t reasons =
        firmware_required ? PAPPL_PREASON_OTHER : PAPPL_PREASON_OFFLINE;
    papplPrinterSetReasons(backend->printer, reasons,
                           PAPPL_PREASON_DEVICE_STATUS & ~reasons);
    papplPrinterReleaseHeldNewJobs(backend->printer, NULL);
    hplj_update_active_jobs(
        backend->printer,
        firmware_required
            ? "firmware-required: import a lawfully acquired, allow-listed firmware file"
            : "held-for-device: reconnect the printer",
        false);
  }
  return true;
}

static bool hplj_rotate_log_by_age(pappl_system_t *system, void *data) {
  struct hplj_pappl_backend *backend = data;
  const time_t now = time(NULL);
  if (now >= 0 && (unsigned long long)now >=
                      backend->retention.maximum_log_age_seconds) {
    const time_t cutoff =
        now - (time_t)backend->retention.maximum_log_age_seconds;
    if (papplSystemRotateLog(system, cutoff)) {
      papplLog(system, PAPPL_LOGLEVEL_INFO, "log-rotation reason=age");
    }
  }
  return true;
}

static void hplj_free_job_data(struct hplj_pappl_job_data *data) {
  if (data != NULL) {
    free(data->page_bits);
    free(data);
  }
}

static bool hplj_device_open(pappl_device_t *device, const char *device_uri,
                             const char *name) {
  (void)device;
  (void)name;
  return strcmp(device_uri, "hplj://reference") == 0;
}

static void hplj_device_close(pappl_device_t *device) {
  (void)device;
}

static ssize_t hplj_device_write(pappl_device_t *device, const void *buffer,
                                 size_t bytes) {
  (void)device;
  (void)buffer;
  return (ssize_t)bytes;
}

static bool hplj_test_device_open(pappl_device_t *device,
                                  const char *device_uri, const char *name) {
  (void)device;
  (void)name;
  return strcmp(device_uri, "hpljtest://fail-write") == 0;
}

static ssize_t hplj_test_device_write(pappl_device_t *device,
                                      const void *buffer, size_t bytes) {
  (void)device;
  (void)buffer;
  (void)bytes;
  return -1;
}

static void hplj_test_trace(struct hplj_pappl_backend *backend,
                            const char *event) {
  if (backend->test_trace < 0 && backend->test_trace_path[0] != '\0') {
    backend->test_trace =
        open(backend->test_trace_path, O_WRONLY | O_APPEND | O_CREAT, 0600);
  }
  if (backend->test_trace >= 0) {
    (void)write(backend->test_trace, event, strlen(event));
  }
}

static enum hplj_error_category hplj_test_discover(
    void *context, struct hplj_usb_descriptor *descriptor) {
  struct hplj_pappl_backend *backend = context;
  descriptor->vendor_id = HPLJ_REFERENCE_VENDOR_ID;
  descriptor->product_id = HPLJ_REFERENCE_PRODUCT_ID;
  hplj_test_trace(backend, "discover\n");
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_test_open(void *context) {
  struct hplj_pappl_backend *backend = context;
  if (backend->test_output < 0) {
    backend->test_output =
        open(backend->test_output_path, O_WRONLY | O_APPEND | O_CREAT, 0600);
  }
  if (backend->test_trace < 0) {
    backend->test_trace =
        open(backend->test_trace_path, O_WRONLY | O_APPEND | O_CREAT, 0600);
  }
  return backend->test_output >= 0 && backend->test_trace >= 0
             ? HPLJ_ERROR_NONE
             : HPLJ_ERROR_DEVICE_ACCESS_DENIED;
}

static enum hplj_error_category hplj_test_claim(void *context) {
  (void)context;
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_test_identity(
    void *context, char *identity, size_t identity_size,
    size_t *identity_length) {
  struct hplj_pappl_backend *backend = context;
  char value[HPLJ_FIRMWARE_VERSION_SIZE + 48];
  int length = backend->test_firmware_uploaded
                   ? snprintf(value, sizeof(value),
                              "MFG:HP;MDL:HP LaserJet 1020;FWVER:%s;",
                              backend->firmware_version)
                   : snprintf(value, sizeof(value),
                              "MFG:HP;MDL:HP LaserJet 1020;");
  if (length <= 0 || (size_t)length + 1 > identity_size ||
      (size_t)length >= sizeof(value)) {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  memcpy(identity, value, (size_t)length + 1);
  *identity_length = (size_t)length;
  hplj_test_trace(backend, backend->test_firmware_uploaded
                               ? "identity-ready\n"
                               : "identity-pre-firmware\n");
  return HPLJ_ERROR_NONE;
}

static enum hplj_error_category hplj_test_upload(
    void *context, const unsigned char *firmware, size_t firmware_size) {
  struct hplj_pappl_backend *backend = context;
  if (firmware == NULL || firmware_size == 0) {
    return HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED;
  }
  backend->test_firmware_uploaded = true;
  hplj_test_trace(backend, "firmware-upload\n");
  return HPLJ_ERROR_NONE;
}

static struct hplj_transfer_result hplj_test_write(
    void *context, const unsigned char *bytes, size_t byte_count) {
  struct hplj_pappl_backend *backend = context;
  if (!atomic_exchange(&backend->test_write_delayed, true)) {
    const struct timespec delay = {.tv_sec = 1, .tv_nsec = 250000000};
    atomic_store(&backend->test_write_in_progress, true);
    (void)nanosleep(&delay, NULL);
  }
  size_t total = 0;
  while (total < byte_count) {
    ssize_t written =
        write(backend->test_output, bytes + total, byte_count - total);
    if (written <= 0) {
      atomic_store(&backend->test_write_in_progress, false);
      return (struct hplj_transfer_result){HPLJ_ERROR_DEVICE_DISCONNECTED,
                                           total};
    }
    total += (size_t)written;
  }
  atomic_store(&backend->test_write_in_progress, false);
  hplj_test_trace(backend, "print-write\n");
  return (struct hplj_transfer_result){HPLJ_ERROR_NONE, total};
}

static enum hplj_error_category hplj_test_status(
    void *context, unsigned int *conditions) {
  struct hplj_pappl_backend *backend = context;
  if (atomic_load(&backend->test_write_in_progress)) {
    hplj_test_trace(backend, "status-during-write\n");
  }
  char value[32] = {0};
  int descriptor = open(backend->test_conditions_path, O_RDONLY);
  if (descriptor < 0) {
    *conditions = HPLJ_DEVICE_CONDITION_NONE;
    return HPLJ_ERROR_NONE;
  }
  ssize_t length = read(descriptor, value, sizeof(value) - 1);
  close(descriptor);
  if (length < 0) {
    return HPLJ_ERROR_DEVICE_DISCONNECTED;
  }
  value[length] = '\0';
  if (strcmp(value, "media-empty\n") == 0) {
    *conditions = HPLJ_DEVICE_CONDITION_MEDIA_EMPTY;
  } else if (strcmp(value, "manual-feed\n") == 0) {
    *conditions = HPLJ_DEVICE_CONDITION_MANUAL_FEED;
  } else if (strcmp(value, "cover-open\n") == 0) {
    *conditions = HPLJ_DEVICE_CONDITION_COVER_OPEN;
  } else {
    return HPLJ_ERROR_DEVICE_PROTOCOL;
  }
  return HPLJ_ERROR_NONE;
}

static void hplj_test_release(void *context) {
  struct hplj_pappl_backend *backend = context;
  if (backend->test_output >= 0) {
    close(backend->test_output);
    backend->test_output = -1;
  }
  if (backend->test_trace >= 0) {
    close(backend->test_trace);
    backend->test_trace = -1;
  }
}

static struct hplj_transfer_result hplj_pappl_write(
    void *context, const unsigned char *bytes, size_t byte_count) {
  struct hplj_pappl_job_data *data = context;
  const ssize_t written = papplDeviceWrite(data->pappl_device, bytes, byte_count);
  if (written < 0) {
    return (struct hplj_transfer_result){HPLJ_ERROR_DEVICE_DISCONNECTED, 0};
  }
  return (struct hplj_transfer_result){
      written == (ssize_t)byte_count ? HPLJ_ERROR_NONE
                                     : HPLJ_ERROR_TRANSFER_INCOMPLETE,
      (size_t)written};
}

static bool hplj_pappl_job_cancelled(void *context, unsigned long job_id) {
  (void)job_id;
  return papplJobIsCanceled(context);
}

static void hplj_pappl_job_state(void *context,
                                 const struct hplj_job_metadata *metadata) {
  pappl_job_t *job = context;
  struct hplj_status status =
      hplj_status_from_job(metadata->state, metadata->error);
  papplJobSetMessage(job, "%s: %s", hplj_status_name(status.code),
                     metadata->error.detail);
}

static bool hplj_printfile(pappl_job_t *job, pappl_pr_options_t *options,
                           pappl_device_t *device) {
  (void)options;
  (void)device;
  papplLogJob(job, PAPPL_LOGLEVEL_ERROR,
              "raw device-format jobs are not accepted");
  return false;
}

static bool hplj_rstartjob(pappl_job_t *job, pappl_pr_options_t *options,
                           pappl_device_t *device) {
  (void)options;
  (void)device;
  struct hplj_pappl_job_data *data = calloc(1, sizeof(*data));
  if (data == NULL) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR,
                "could not allocate raster job state");
    return false;
  }
  pappl_pr_driver_data_t driver_data;
  papplPrinterGetDriverData(papplJobGetPrinter(job), &driver_data);
  struct hplj_pappl_backend *backend = driver_data.extension;
  data->pappl_device = device;
  struct hplj_device *transport;
  const unsigned char *firmware = NULL;
  size_t firmware_size = 0;
  const char *firmware_version = "pappl-managed";
  if (backend != NULL && backend->owns_device) {
    transport = &backend->device;
  } else {
    struct hplj_device_ops ops = {
        .write = hplj_pappl_write,
        .context = data,
    };
    hplj_device_init(&data->transport, &ops);
    data->transport.state = HPLJ_DEVICE_READY;
    papplCopyString(data->transport.firmware_version, firmware_version,
                    sizeof(data->transport.firmware_version));
    transport = &data->transport;
  }
  hplj_job_init(&data->lifecycle, (unsigned long)papplJobGetID(job),
                transport, hplj_foo2zjs_model_1(),
                hplj_pappl_job_cancelled, hplj_pappl_job_state, job);
  papplJobSetData(job, data);
  if (papplJobIsCanceled(job)) {
    hplj_free_job_data(data);
    papplJobSetData(job, NULL);
    return false;
  }
  if (backend != NULL && backend->owns_device) {
    if (!hplj_wait_for_ready(backend, job, NULL)) {
      hplj_free_job_data(data);
      papplJobSetData(job, NULL);
      return false;
    }
    pthread_mutex_lock(&backend->device_mutex);
    firmware = backend->firmware;
    firmware_size = backend->firmware_size;
    firmware_version = backend->firmware_version;
  }
  struct hplj_error error =
      hplj_job_prepare(&data->lifecycle, firmware, firmware_size,
                       firmware_version);
  if (backend != NULL && backend->owns_device) {
    pthread_mutex_unlock(&backend->device_mutex);
  }
  if (error.category != HPLJ_ERROR_NONE) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR, "%s", error.detail);
    hplj_free_job_data(data);
    papplJobSetData(job, NULL);
    return false;
  }
  return true;
}

static bool hplj_rendjob(pappl_job_t *job, pappl_pr_options_t *options,
                         pappl_device_t *device) {
  (void)options;
  struct hplj_pappl_job_data *data = papplJobGetData(job);
  bool completed = false;
  if (data != NULL) {
    if (papplJobIsCanceled(job)) {
      hplj_job_cancel(&data->lifecycle);
    } else if (data->lifecycle.metadata.state == HPLJ_JOB_PREPARING) {
      completed = hplj_job_complete(&data->lifecycle).category == HPLJ_ERROR_NONE;
    }
  }
  hplj_free_job_data(data);
  papplJobSetData(job, NULL);
  papplDeviceFlush(device);
  return completed;
}

static enum hplj_media hplj_media_from_name(const char *name) {
  return name != NULL && strcmp(name, "na_letter_8.5x11in") == 0
             ? HPLJ_MEDIA_LETTER
             : HPLJ_MEDIA_A4;
}

static bool hplj_rstartpage(pappl_job_t *job, pappl_pr_options_t *options,
                            pappl_device_t *device, unsigned page) {
  (void)device;
  (void)page;
  cups_page_header_t *header = &options->header;
  struct hplj_job_attributes attributes = {
      .format = HPLJ_DOCUMENT_PWG_RASTER,
      .resolution_dpi = header->HWResolution[0],
      .bits_per_pixel = header->cupsBitsPerPixel,
      .media = hplj_media_from_name(options->media.size_name),
      .source = HPLJ_SOURCE_AUTO,
      .quality = options->print_quality == IPP_QUALITY_NORMAL
                     ? HPLJ_QUALITY_NORMAL
                     : HPLJ_QUALITY_HIGH,
      .density = 3,
  };
  struct hplj_error error = hplj_pappl_validate_job(&attributes);
  if (error.category != HPLJ_ERROR_NONE) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR, "%s", error.detail);
    return false;
  }
  if (header->HWResolution[1] != 600 || header->cupsWidth == 0 ||
      header->cupsHeight == 0 || header->cupsBitsPerPixel != 1 ||
      header->cupsBytesPerLine < (header->cupsWidth + 7U) / 8U ||
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxLeft] >
          header->cupsInteger[CUPS_RASTER_PWG_ImageBoxRight] ||
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxRight] >= header->cupsWidth ||
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxTop] >
          header->cupsInteger[CUPS_RASTER_PWG_ImageBoxBottom] ||
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxBottom] >= header->cupsHeight ||
      header->cupsHeight > SIZE_MAX / header->cupsBytesPerLine) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR,
                "raster header geometry is unsupported");
    return false;
  }
  struct hplj_pappl_job_data *data = papplJobGetData(job);
  if (data == NULL) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR, "raster job state is missing");
    return false;
  }
  if (papplJobIsCanceled(job)) {
    return false;
  }
  pappl_pr_driver_data_t driver_data;
  papplPrinterGetDriverData(papplJobGetPrinter(job), &driver_data);
  struct hplj_pappl_backend *backend = driver_data.extension;
  if (backend != NULL && backend->owns_device) {
    if (!hplj_wait_for_ready(backend, job, &data->lifecycle)) {
      return false;
    }
  }
  free(data->page_bits);
  data->page_size = header->cupsBytesPerLine * header->cupsHeight;
  data->page_bits = malloc(data->page_size);
  data->rows_received = 0;
  if (data->page_bits == NULL) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR,
                "could not allocate raster page buffer");
    return false;
  }
  return true;
}

static bool hplj_rwriteline(pappl_job_t *job, pappl_pr_options_t *options,
                            pappl_device_t *device, unsigned y,
                            const unsigned char *line) {
  if (papplJobIsCanceled(job)) {
    return false;
  }
  struct hplj_pappl_job_data *data = papplJobGetData(job);
  size_t bytes = options->header.cupsBytesPerLine;
  (void)device;
  if (data == NULL || data->page_bits == NULL || line == NULL ||
      y != data->rows_received || y >= options->header.cupsHeight ||
      bytes > data->page_size - (size_t)y * bytes) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR,
                "raster page rows are incomplete or out of order");
    return false;
  }
  memcpy(data->page_bits + (size_t)y * bytes, line, bytes);
  data->rows_received++;
  return true;
}

static bool hplj_rendpage(pappl_job_t *job, pappl_pr_options_t *options,
                          pappl_device_t *device, unsigned page) {
  (void)page;
  struct hplj_pappl_job_data *data = papplJobGetData(job);
  cups_page_header_t *header = &options->header;
  if (data == NULL || data->page_bits == NULL ||
      data->rows_received != header->cupsHeight || papplJobIsCanceled(job)) {
    return false;
  }
  const unsigned int left =
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxLeft];
  const unsigned int right =
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxRight];
  const unsigned int top =
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxTop];
  const unsigned int bottom =
      header->cupsInteger[CUPS_RASTER_PWG_ImageBoxBottom];
  const struct hplj_raster raster = {
      .width_pixels = header->cupsWidth,
      .height_rows = header->cupsHeight,
      .resolution_dpi = header->HWResolution[0],
      .painted_resolution_dpi = header->HWResolution[1],
      .page_width_pixels = header->cupsWidth,
      .page_height_rows = header->cupsHeight,
      .printable_x_pixels = left,
      .printable_y_rows = top,
      .printable_width_pixels = right - left + 1U,
      .printable_height_rows = bottom - top + 1U,
      .row_stride_bytes = header->cupsBytesPerLine,
      .bits = data->page_bits,
      .bits_size = data->page_size,
      .bit_polarity = HPLJ_BLACK_IS_ONE,
      .bit_order = HPLJ_MOST_SIGNIFICANT_BIT_FIRST,
      .page_count = 1,
      .media = hplj_media_from_name(options->media.size_name),
      .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL,
      .density = 3,
  };
  (void)device;
  pappl_pr_driver_data_t driver_data;
  papplPrinterGetDriverData(papplJobGetPrinter(job), &driver_data);
  struct hplj_pappl_backend *backend = driver_data.extension;
  if (backend != NULL && backend->owns_device) {
    pthread_mutex_lock(&backend->device_mutex);
  }
  const struct hplj_error result =
      hplj_job_submit_page(&data->lifecycle, &raster);
  if (backend != NULL && backend->owns_device) {
    pthread_mutex_unlock(&backend->device_mutex);
  }
  free(data->page_bits);
  data->page_bits = NULL;
  data->page_size = 0;
  data->rows_received = 0;
  if (result.category != HPLJ_ERROR_NONE) {
    papplLogJob(job, PAPPL_LOGLEVEL_ERROR, "%s", result.detail);
    return false;
  }
  papplDeviceFlush(device);
  return true;
}

static bool hplj_driver(pappl_system_t *system, const char *driver_name,
                        const char *device_uri, const char *device_id,
                        pappl_pr_driver_data_t *data, ipp_t **driver_attrs,
                        void *context) {
  (void)system;
  (void)device_uri;
  (void)device_id;
  (void)driver_attrs;
  (void)context;
  if (driver_name == NULL || strcmp(driver_name, HPLJ_DRIVER_NAME) != 0 ||
      data == NULL) {
    return false;
  }
  data->extension = context;
  const struct hplj_capability_profile *profile = hplj_pappl_capabilities();
  data->rstartjob_cb = hplj_rstartjob;
  data->printfile_cb = hplj_printfile;
  data->rstartpage_cb = hplj_rstartpage;
  data->rwriteline_cb = hplj_rwriteline;
  data->rendpage_cb = hplj_rendpage;
  data->rendjob_cb = hplj_rendjob;
  data->format = "application/vnd.hp-zjs";
  papplCopyString(data->make_and_model, "HP LaserJet 1020",
                  sizeof(data->make_and_model));
  data->ppm = 15;
  data->orient_default = IPP_ORIENT_NONE;
  data->quality_default = profile->quality == HPLJ_QUALITY_NORMAL
                              ? IPP_QUALITY_NORMAL
                              : IPP_QUALITY_DRAFT;
  data->num_resolution = 1;
  data->x_resolution[0] = (int)profile->resolution_dpi;
  data->y_resolution[0] = (int)profile->resolution_dpi;
  data->x_default = (int)profile->resolution_dpi;
  data->y_default = (int)profile->resolution_dpi;
  data->raster_types = profile->bits_per_pixel == 1
                           ? PAPPL_PWG_RASTER_TYPE_BLACK_1
                           : PAPPL_PWG_RASTER_TYPE_BLACK_8;
  data->force_raster_type = data->raster_types;
  data->color_supported = PAPPL_COLOR_MODE_BI_LEVEL;
  data->color_default = PAPPL_COLOR_MODE_BI_LEVEL;
  data->num_media = 2;
  data->media[0] = "iso_a4_210x297mm";
  data->media[1] = "na_letter_8.5x11in";
  papplCopyString(data->media_default.size_name, data->media[0],
                  sizeof(data->media_default.size_name));
  data->num_source = 1;
  data->source[0] = "auto";
  papplCopyString(data->media_default.source, data->source[0],
                  sizeof(data->media_default.source));
  data->sides_supported = PAPPL_SIDES_ONE_SIDED;
  data->sides_default = PAPPL_SIDES_ONE_SIDED;
  return true;
}

static void *hplj_backend_create(void *context,
                                 const struct hplj_service_config *config) {
  (void)context;
  struct hplj_pappl_backend *backend = calloc(1, sizeof(*backend));
  if (backend == NULL) {
    return NULL;
  }
  if (pthread_mutex_init(&backend->device_mutex, NULL) != 0) {
    free(backend);
    return NULL;
  }
  atomic_init(&backend->stopping, false);
  atomic_init(&backend->device_error, HPLJ_ERROR_NONE);
  atomic_init(&backend->test_write_delayed, false);
  atomic_init(&backend->test_write_in_progress, false);
  backend->test_output = -1;
  backend->test_trace = -1;
  backend->firmware_path = config->paths.firmware_path;
  const char test_prefix[] = "hpljtest:///";
  backend->test_device =
      strncmp(config->device_uri, test_prefix, sizeof(test_prefix) - 1) == 0;
  backend->owns_device = strncmp(config->device_uri, "usb://", 6) == 0 ||
                         backend->test_device;
  if (backend->test_device) {
    const char *output_path = config->device_uri + sizeof("hpljtest://") - 1;
    if (output_path[0] != '/' ||
        snprintf(backend->test_output_path, sizeof(backend->test_output_path),
                 "%s", output_path) >= (int)sizeof(backend->test_output_path) ||
        snprintf(backend->test_trace_path, sizeof(backend->test_trace_path),
                 "%s.trace", output_path) >= (int)sizeof(backend->test_trace_path)) {
      pthread_mutex_destroy(&backend->device_mutex);
      free(backend);
      return NULL;
    }
    if (snprintf(backend->test_conditions_path,
                 sizeof(backend->test_conditions_path), "%s.conditions",
                 output_path) >= (int)sizeof(backend->test_conditions_path)) {
      pthread_mutex_destroy(&backend->device_mutex);
      free(backend);
      return NULL;
    }
  }
  if (strcmp(config->device_uri, "hpljtest://fail-write") == 0) {
    papplDeviceAddScheme("hpljtest", PAPPL_DEVTYPE_CUSTOM_LOCAL, NULL,
                         hplj_test_device_open, hplj_device_close, NULL,
                         hplj_test_device_write, NULL, NULL);
  }
  if (backend->owns_device) {
    struct hplj_device_ops ops;
    if (backend->test_device) {
      ops = (struct hplj_device_ops){
          .discover = hplj_test_discover,
          .open = hplj_test_open,
          .claim_interface = hplj_test_claim,
          .read_identity = hplj_test_identity,
          .upload_firmware = hplj_test_upload,
          .write = hplj_test_write,
          .read_status = hplj_test_status,
          .release = hplj_test_release,
          .context = backend,
      };
    } else {
      if (hplj_libusb_transport_create(&backend->usb) != HPLJ_ERROR_NONE) {
        pthread_mutex_destroy(&backend->device_mutex);
        free(backend);
        return NULL;
      }
      hplj_libusb_device_ops(backend->usb, &ops);
    }
    hplj_device_init(&backend->device, &ops);
    papplDeviceAddScheme("hplj", PAPPL_DEVTYPE_CUSTOM_LOCAL, NULL,
                         hplj_device_open, hplj_device_close, NULL,
                         hplj_device_write, NULL, NULL);
  }
  backend->system = papplSystemCreate(
      PAPPL_SOPTIONS_NO_TLS, "HP LaserJet 1020", config->ipp_port, NULL,
      config->paths.spool_path, config->paths.log_path, PAPPL_LOGLEVEL_INFO,
      NULL, false);
  if (backend->system == NULL) {
    hplj_libusb_transport_destroy(backend->usb);
    pthread_mutex_destroy(&backend->device_mutex);
    free(backend);
    return NULL;
  }
  static pappl_pr_driver_t drivers[] = {
      {HPLJ_DRIVER_NAME, "HP LaserJet 1020", "MFG:HP;MDL:HP LaserJet 1020;", NULL},
  };
  papplSystemSetDNSSDName(backend->system, NULL);
  papplSystemSetMaxLogSize(backend->system, HPLJ_MAX_LOG_BYTES);
  papplSystemSetPrinterDrivers(backend->system, 1, drivers, NULL, NULL,
                               hplj_driver, backend);
  return backend;
}

static bool hplj_report_ready(pappl_system_t *system, void *data) {
  (void)system;
  (void)data;
  printf("READY %s %u\n", HPLJ_IPV4_LOOPBACK, HPLJ_IPP_PORT);
  fflush(stdout);
  return false;
}

static bool hplj_backend_add_listener(void *service, const char *address) {
  struct hplj_pappl_backend *backend = service;
  return papplSystemAddListeners(backend->system, address);
}

static bool hplj_backend_load_state(void *service, const char *path) {
  struct hplj_pappl_backend *backend = service;
  return access(path, F_OK) != 0 || papplSystemLoadState(backend->system, path);
}

static void hplj_find_queue(pappl_printer_t *printer, void *data) {
  struct hplj_queue_lookup *lookup = data;
  if (strcmp(papplPrinterGetName(printer), lookup->name) == 0) {
    lookup->printer = printer;
  }
}

static bool hplj_backend_reconcile(void *service, const char *queue_name,
                                   const char *driver_name,
                                   const char *device_uri) {
  struct hplj_pappl_backend *backend = service;
  const char *runtime_device_uri =
      backend->owns_device ? "hplj://reference" : device_uri;
  struct hplj_queue_lookup lookup = {.name = queue_name, .printer = NULL};
  papplSystemIteratePrinters(backend->system, hplj_find_queue, &lookup);
  if (lookup.printer != NULL) {
    backend->printer = lookup.printer;
    bool matches =
        strcmp(papplPrinterGetDriverName(lookup.printer), driver_name) == 0 &&
        strcmp(papplPrinterGetDeviceURI(lookup.printer), runtime_device_uri) == 0;
    if (matches && backend->owns_device) {
      hplj_monitor_device(backend->system, backend);
    }
    return matches;
  }
  pappl_printer_t *printer = papplPrinterCreate(
      backend->system, 0, queue_name, driver_name,
      "MFG:HP;MDL:HP LaserJet 1020;", runtime_device_uri);
  if (printer == NULL) {
    return false;
  }
  papplPrinterSetDNSSDName(printer, NULL);
  papplPrinterSetMaxCompletedJobs(printer, 0);
  papplPrinterSetMaxPreservedJobs(printer, 0);
  papplPrinterSetMaxActiveJobs(printer, 0);
  backend->printer = printer;
  if (backend->owns_device) {
    hplj_monitor_device(backend->system, backend);
  }
  return true;
}

static bool hplj_backend_configure_policy(
    void *service, const struct hplj_retention_policy *policy) {
  struct hplj_pappl_backend *backend = service;
  if (backend->printer == NULL || policy == NULL ||
      policy->maximum_completed_jobs == 0 ||
      policy->maximum_log_bytes == 0 ||
      policy->maximum_log_age_seconds == 0) {
    return false;
  }
  papplPrinterSetMaxCompletedJobs(backend->printer,
                                  (int)policy->maximum_completed_jobs);
  papplPrinterSetMaxPreservedJobs(backend->printer, 0);
  papplSystemSetMaxLogSize(backend->system, policy->maximum_log_bytes);
  backend->retention = *policy;
  return true;
}

static bool hplj_backend_run(void *service) {
  struct hplj_pappl_backend *backend = service;
  papplSystemRun(backend->system);
  return true;
}

static void hplj_backend_shutdown(void *service) {
  struct hplj_pappl_backend *backend = service;
  atomic_store(&backend->stopping, true);
  papplSystemShutdown(backend->system);
}

static bool hplj_backend_save_state(void *service, const char *path) {
  struct hplj_pappl_backend *backend = service;
  return papplSystemSaveState(backend->system, path);
}

static void hplj_backend_destroy(void *service) {
  struct hplj_pappl_backend *backend = service;
  papplSystemDelete(backend->system);
  if (backend->owns_device) {
    hplj_device_disconnect(&backend->device);
  }
  hplj_libusb_transport_destroy(backend->usb);
  pthread_mutex_destroy(&backend->device_mutex);
  free(backend->firmware);
  free(backend);
}

int hplj_pappl_serve(const struct hplj_service_config *config) {
  struct hplj_service service;
  struct hplj_service_ops ops = {
      .create = hplj_backend_create,
      .add_listener = hplj_backend_add_listener,
      .load_state = hplj_backend_load_state,
      .reconcile_queue = hplj_backend_reconcile,
      .configure_policy = hplj_backend_configure_policy,
      .run = hplj_backend_run,
      .shutdown = hplj_backend_shutdown,
      .save_state = hplj_backend_save_state,
      .destroy = hplj_backend_destroy,
  };
  struct hplj_error error = hplj_service_prepare(&service, config, &ops);
  if (error.category != HPLJ_ERROR_NONE) {
    fprintf(stderr, "hplj1020: %s\n", error.detail);
    return 1;
  }
  struct hplj_pappl_backend *backend = service.backend;
  time_t now = time(NULL);
  if (!papplSystemAddTimerCallback(backend->system, now, 0,
                                   hplj_report_ready, NULL)) {
    (void)hplj_service_finish(&service);
    return 1;
  }
  if (backend->owns_device &&
      !papplSystemAddTimerCallback(backend->system, now + 1, 1,
                                   hplj_monitor_device, backend)) {
    (void)hplj_service_finish(&service);
    return 1;
  }
  if (!papplSystemAddTimerCallback(backend->system, now, 60U * 60U,
                                   hplj_rotate_log_by_age, backend)) {
    (void)hplj_service_finish(&service);
    return 1;
  }
  error = hplj_service_run(&service);
  struct hplj_error finish_error = hplj_service_finish(&service);
  return error.category == HPLJ_ERROR_NONE &&
                 finish_error.category == HPLJ_ERROR_NONE
             ? 0
             : 1;
}
