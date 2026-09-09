// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"
#include "hplj/job.h"

#include <assert.h>
#include <stdbool.h>
#include <string.h>

struct fake_service {
  unsigned int creates;
  unsigned int listeners;
  unsigned int reconciles;
  unsigned int runs;
  unsigned int shutdowns;
  unsigned int saves;
  unsigned int destroys;
  unsigned int policies;
  unsigned int maximum_completed_jobs;
  size_t maximum_log_bytes;
  unsigned long maximum_log_age_seconds;
  const char *addresses[3];
  const char *queue_name;
  const char *driver_name;
  const char *device_uri;
  bool fail_reconcile;
  bool fail_policy;
};

static bool fake_configure_policy(void *service,
                                  const struct hplj_retention_policy *policy) {
  struct fake_service *fake = service;
  fake->policies++;
  fake->maximum_completed_jobs = policy->maximum_completed_jobs;
  fake->maximum_log_bytes = policy->maximum_log_bytes;
  fake->maximum_log_age_seconds = policy->maximum_log_age_seconds;
  return !fake->fail_policy;
}

static void *fake_create(void *context, const struct hplj_service_config *config) {
  struct fake_service *fake = context;
  fake->creates++;
  assert(config->ipp_port == HPLJ_IPP_PORT);
  return fake;
}

static bool fake_add_listener(void *service, const char *address) {
  struct fake_service *fake = service;
  fake->addresses[fake->listeners++] = address;
  return true;
}

static bool fake_load_state(void *service, const char *path) {
  (void)service;
  assert(strcmp(path, "/private/state/system.state") == 0);
  return true;
}

static bool fake_reconcile(void *service, const char *queue_name,
                           const char *driver_name, const char *device_uri) {
  struct fake_service *fake = service;
  fake->reconciles++;
  fake->queue_name = queue_name;
  fake->driver_name = driver_name;
  fake->device_uri = device_uri;
  return !fake->fail_reconcile;
}

static bool fake_run(void *service) {
  struct fake_service *fake = service;
  fake->runs++;
  return true;
}

static void fake_shutdown(void *service) {
  struct fake_service *fake = service;
  fake->shutdowns++;
}

static bool fake_save_state(void *service, const char *path) {
  struct fake_service *fake = service;
  fake->saves++;
  assert(strcmp(path, "/private/state/system.state") == 0);
  return true;
}

static void fake_destroy(void *service) {
  struct fake_service *fake = service;
  fake->destroys++;
}

static struct hplj_service_ops fake_ops(struct fake_service *fake) {
  return (struct hplj_service_ops){
      .create = fake_create,
      .add_listener = fake_add_listener,
      .load_state = fake_load_state,
      .reconcile_queue = fake_reconcile,
      .configure_policy = fake_configure_policy,
      .run = fake_run,
      .shutdown = fake_shutdown,
      .save_state = fake_save_state,
      .destroy = fake_destroy,
      .context = fake,
  };
}

static struct hplj_service_config test_config(void) {
  return (struct hplj_service_config){
      .queue_name = HPLJ_QUEUE_NAME,
      .loopback_host = HPLJ_IPV4_LOOPBACK,
      .ipp_port = HPLJ_IPP_PORT,
      .paths = {
          .firmware_path = "/private/firmware",
          .state_path = "/private/state/system.state",
          .spool_path = "/private/spool",
          .log_path = "/private/log/service.log",
          .socket_path = "/private/run/service.sock",
      },
      .device_uri = "file:///private/fake-device",
  };
}

static void test_prepare_is_loopback_only_and_reconciles_one_queue(void) {
  struct fake_service fake = {0};
  struct hplj_service service;
  struct hplj_service_ops ops = fake_ops(&fake);
  struct hplj_service_config config = test_config();

  struct hplj_error error = hplj_service_prepare(&service, &config, &ops);
  assert(error.category == HPLJ_ERROR_NONE);
  assert(hplj_service_is_ready(&service));
  assert(fake.creates == 1);
  assert(fake.listeners == 3);
  assert(strcmp(fake.addresses[0], HPLJ_IPV4_LOOPBACK) == 0);
  assert(strcmp(fake.addresses[1], HPLJ_IPV6_LOOPBACK) == 0);
  assert(strcmp(fake.addresses[2], config.paths.socket_path) == 0);
  assert(fake.reconciles == 1);
  assert(fake.policies == 1);
  assert(fake.maximum_completed_jobs == 20);
  assert(fake.maximum_log_bytes == 10U * 1024U * 1024U);
  assert(fake.maximum_log_age_seconds == 14U * 24U * 60U * 60U);
  assert(strcmp(fake.queue_name, HPLJ_QUEUE_NAME) == 0);
  assert(strcmp(fake.driver_name, HPLJ_DRIVER_NAME) == 0);
  assert(strcmp(fake.device_uri, config.device_uri) == 0);

  assert(hplj_service_run(&service).category == HPLJ_ERROR_NONE);
  hplj_service_request_shutdown(&service);
  assert(hplj_service_finish(&service).category == HPLJ_ERROR_NONE);
  assert(fake.runs == 1);
  assert(fake.shutdowns == 1);
  assert(fake.saves == 1);
  assert(fake.destroys == 1);
}

static void test_status_mapping_is_stable_and_actionable(void) {
  for (enum hplj_error_category category = HPLJ_ERROR_NONE;
       category < HPLJ_ERROR_CATEGORY_COUNT; category++) {
    assert(strcmp(hplj_error_category_name(category), "unknown") != 0);
  }
  assert(strcmp(hplj_error_category_name(HPLJ_ERROR_MEDIA_EMPTY),
                "media-empty") == 0);
  assert(strcmp(hplj_error_category_name(HPLJ_ERROR_CANCELLED),
                "canceled") == 0);

  struct hplj_status status = hplj_status_from_error(hplj_error_make(
      HPLJ_ERROR_DEVICE_DISCONNECTED, HPLJ_RETRY_EXPLICIT,
      HPLJ_ACTION_RECONNECT_PRINTER, "transport disappeared"));
  assert(status.code == HPLJ_STATUS_DEVICE_DISCONNECTED);
  assert(status.queue == HPLJ_QUEUE_HELD);
  assert(status.diagnostic == HPLJ_ERROR_DEVICE_DISCONNECTED);
  assert(strcmp(hplj_status_name(status.code), "device-disconnected") == 0);

  status = hplj_status_from_conditions(HPLJ_DEVICE_CONDITION_MEDIA_EMPTY);
  assert(status.code == HPLJ_STATUS_MEDIA_EMPTY);
  assert(status.action == HPLJ_ACTION_LOAD_MEDIA);
  assert(status.diagnostic == HPLJ_ERROR_MEDIA_EMPTY);

  status = hplj_status_from_conditions(HPLJ_DEVICE_CONDITION_MANUAL_FEED);
  assert(status.code == HPLJ_STATUS_MANUAL_FEED);
  assert(status.action == HPLJ_ACTION_LOAD_MANUAL_FEED);

  status = hplj_status_from_conditions(HPLJ_DEVICE_CONDITION_COVER_OPEN);
  assert(status.code == HPLJ_STATUS_COVER_OPEN);
  assert(status.action == HPLJ_ACTION_CLOSE_COVER);

  status = hplj_status_from_device(HPLJ_DEVICE_PRE_FIRMWARE);
  assert(status.code == HPLJ_STATUS_FIRMWARE_REQUIRED);
  assert(status.action == HPLJ_ACTION_IMPORT_FIRMWARE);
  assert(status.diagnostic == HPLJ_ERROR_FIRMWARE_MISSING);

  status = hplj_status_from_error(hplj_error_make(
      HPLJ_ERROR_FIRMWARE_STORAGE_FAILED, HPLJ_RETRY_EXPLICIT,
      HPLJ_ACTION_RETRY_FIRMWARE_IMPORT, "firmware storage failed"));
  assert(status.code == HPLJ_STATUS_FIRMWARE_FAILED);
  assert(status.action == HPLJ_ACTION_RETRY_FIRMWARE_IMPORT);
  assert(status.diagnostic == HPLJ_ERROR_FIRMWARE_STORAGE_FAILED);

  status = hplj_status_from_error(hplj_error_make(
      HPLJ_ERROR_ENCODING_FAILED, HPLJ_RETRY_SAFE_AUTOMATIC,
      HPLJ_ACTION_RETRY_JOB, "encoding failed"));
  assert(status.code == HPLJ_STATUS_ENCODING_FAILED);
  status = hplj_status_from_error(hplj_error_make(
      HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
      "canceled"));
  assert(status.code == HPLJ_STATUS_CANCELED);

  status = hplj_status_from_job(
      HPLJ_JOB_FAILED_PARTIAL,
      hplj_error_make(HPLJ_ERROR_DEVICE_TIMEOUT, HPLJ_RETRY_EXPLICIT,
                      HPLJ_ACTION_RETRY_JOB, "partial output"));
  assert(status.code == HPLJ_STATUS_TRANSFER_FAILED);
  assert(status.queue == HPLJ_QUEUE_HELD);
}

static void test_log_rotation_policy_uses_whichever_bound_arrives_first(void) {
  const unsigned long long day = 24U * 60U * 60U;
  const struct hplj_retention_policy policy = {
      HPLJ_MAX_COMPLETED_JOBS, HPLJ_MAX_LOG_BYTES,
      HPLJ_MAX_LOG_AGE_SECONDS};
  assert(!hplj_log_rotation_due(1024, 100, 100 + 13U * day, &policy));
  assert(hplj_log_rotation_due(HPLJ_MAX_LOG_BYTES, 100, 101, &policy));
  assert(hplj_log_rotation_due(1024, 100, 100 + 14U * day, &policy));
  assert(!hplj_log_rotation_due(1024, 200, 100, &policy));
}

static void test_invalid_configuration_never_creates_a_listener(void) {
  struct fake_service fake = {0};
  struct hplj_service service;
  struct hplj_service_ops ops = fake_ops(&fake);
  struct hplj_service_config config = test_config();
  config.ipp_port = 0;

  struct hplj_error error = hplj_service_prepare(&service, &config, &ops);
  assert(error.category == HPLJ_ERROR_INVALID_STATE);
  assert(fake.creates == 0);
  assert(fake.listeners == 0);
}

static void test_queue_reconciliation_has_a_structured_failure(void) {
  struct fake_service fake = {.fail_reconcile = true};
  struct hplj_service service;
  struct hplj_service_ops ops = fake_ops(&fake);
  struct hplj_service_config config = test_config();

  struct hplj_error error = hplj_service_prepare(&service, &config, &ops);
  assert(error.category == HPLJ_ERROR_QUEUE_UNAVAILABLE);
  assert(error.action == HPLJ_ACTION_RETRY_QUEUE);
  assert(fake.reconciles == 1);
  assert(fake.policies == 0);
  assert(fake.destroys == 1);
}

static void test_policy_failure_prevents_service_start(void) {
  struct fake_service fake = {.fail_policy = true};
  struct hplj_service service;
  struct hplj_service_ops ops = fake_ops(&fake);
  struct hplj_service_config config = test_config();

  struct hplj_error error = hplj_service_prepare(&service, &config, &ops);
  assert(error.category == HPLJ_ERROR_INVALID_STATE);
  assert(fake.reconciles == 1);
  assert(fake.policies == 1);
  assert(fake.destroys == 1);
}

static void test_unsupported_job_attributes_fail_before_output(void) {
  struct hplj_job_attributes job = {
      .format = HPLJ_DOCUMENT_PWG_RASTER,
      .resolution_dpi = 300,
      .bits_per_pixel = 1,
      .media = HPLJ_MEDIA_A4,
      .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL,
      .density = 3,
  };
  struct hplj_error error = hplj_pappl_validate_job(&job);
  assert(error.category == HPLJ_ERROR_RASTER_INVALID);
  assert(error.retry == HPLJ_RETRY_NEVER);

  job.resolution_dpi = 600;
  job.format = HPLJ_DOCUMENT_PDF;
  error = hplj_pappl_validate_job(&job);
  assert(error.category == HPLJ_ERROR_RASTER_INVALID);

  job.format = HPLJ_DOCUMENT_APPLE_RASTER;
  assert(hplj_pappl_validate_job(&job).category == HPLJ_ERROR_NONE);
  job.format = HPLJ_DOCUMENT_PWG_RASTER;
  assert(hplj_pappl_validate_job(&job).category == HPLJ_ERROR_NONE);
}

int main(void) {
  test_prepare_is_loopback_only_and_reconciles_one_queue();
  test_invalid_configuration_never_creates_a_listener();
  test_queue_reconciliation_has_a_structured_failure();
  test_policy_failure_prevents_service_start();
  test_unsupported_job_attributes_fail_before_output();
  test_status_mapping_is_stable_and_actionable();
  test_log_rotation_policy_uses_whichever_bound_arrives_first();
  return 0;
}
