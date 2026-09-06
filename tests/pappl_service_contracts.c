// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"

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
  const char *addresses[3];
  const char *queue_name;
  const char *driver_name;
  const char *device_uri;
};

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
  return true;
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
  test_unsupported_job_attributes_fail_before_output();
  return 0;
}
