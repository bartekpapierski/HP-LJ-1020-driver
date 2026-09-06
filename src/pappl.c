// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"

#include <string.h>

static struct hplj_error hplj_pappl_error(enum hplj_error_category category,
                                           const char *detail) {
  return hplj_error_make(category,
                         category == HPLJ_ERROR_NONE ? HPLJ_RETRY_SAFE_AUTOMATIC
                                                     : HPLJ_RETRY_NEVER,
                         category == HPLJ_ERROR_RASTER_INVALID
                             ? HPLJ_ACTION_CORRECT_RASTER
                             : HPLJ_ACTION_NONE,
                         detail);
}

const struct hplj_capability_profile *hplj_pappl_capabilities(void) {
  static const struct hplj_capability_profile profile = {
      .resolution_dpi = 600,
      .bits_per_pixel = 1,
      .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL,
      .density = 3,
  };
  return &profile;
}

static bool hplj_pappl_supports_format(enum hplj_document_format format) {
  return format == HPLJ_DOCUMENT_PWG_RASTER ||
         format == HPLJ_DOCUMENT_APPLE_RASTER;
}

static bool hplj_pappl_supports_media(enum hplj_media media) {
  return media == HPLJ_MEDIA_A4 || media == HPLJ_MEDIA_LETTER;
}

struct hplj_error hplj_pappl_validate_job(const struct hplj_job_attributes *job) {
  const struct hplj_capability_profile *profile = hplj_pappl_capabilities();
  if (job == NULL) {
    return hplj_pappl_error(HPLJ_ERROR_RASTER_INVALID, "job attributes are missing");
  }
  if (!hplj_pappl_supports_format(job->format)) {
    return hplj_pappl_error(HPLJ_ERROR_RASTER_INVALID,
                            "document format is not supported");
  }
  if (job->resolution_dpi != profile->resolution_dpi ||
      job->bits_per_pixel != profile->bits_per_pixel) {
    return hplj_pappl_error(HPLJ_ERROR_RASTER_INVALID,
                            "raster must be one-bit 600 by 600 dpi");
  }
  if (!hplj_pappl_supports_media(job->media) ||
      job->source != profile->source || job->quality != profile->quality ||
      job->density != profile->density) {
    return hplj_pappl_error(HPLJ_ERROR_RASTER_INVALID,
                            "job options are outside the verified capability envelope");
  }
  return hplj_pappl_error(HPLJ_ERROR_NONE, "job attributes accepted");
}

static bool hplj_service_config_valid(const struct hplj_service_config *config) {
  return config != NULL && config->queue_name != NULL &&
         strcmp(config->queue_name, HPLJ_QUEUE_NAME) == 0 &&
         config->loopback_host != NULL &&
         strcmp(config->loopback_host, HPLJ_IPV4_LOOPBACK) == 0 &&
         config->ipp_port == HPLJ_IPP_PORT && config->paths.state_path != NULL &&
         config->paths.spool_path != NULL && config->paths.log_path != NULL &&
         config->paths.socket_path != NULL && config->paths.socket_path[0] == '/' &&
         config->device_uri != NULL;
}

static bool hplj_service_ops_valid(const struct hplj_service_ops *ops) {
  return ops != NULL && ops->create != NULL && ops->add_listener != NULL &&
         ops->load_state != NULL && ops->reconcile_queue != NULL &&
         ops->run != NULL && ops->shutdown != NULL && ops->save_state != NULL &&
         ops->destroy != NULL;
}

struct hplj_error hplj_service_prepare(struct hplj_service *service,
                                       const struct hplj_service_config *config,
                                       const struct hplj_service_ops *ops) {
  if (service == NULL) {
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE, "service storage is missing");
  }
  memset(service, 0, sizeof(*service));
  if (!hplj_service_config_valid(config) || !hplj_service_ops_valid(ops)) {
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                            "invalid PAPPL service configuration");
  }
  service->ops = *ops;
  service->state_path = config->paths.state_path;
  service->backend = ops->create(ops->context, config);
  if (service->backend == NULL) {
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                            "could not create PAPPL system");
  }
  if (!ops->add_listener(service->backend, HPLJ_IPV4_LOOPBACK) ||
      !ops->add_listener(service->backend, HPLJ_IPV6_LOOPBACK) ||
      !ops->add_listener(service->backend, config->paths.socket_path) ||
      !ops->load_state(service->backend, config->paths.state_path) ||
      !ops->reconcile_queue(service->backend, HPLJ_QUEUE_NAME, HPLJ_DRIVER_NAME,
                            config->device_uri)) {
    ops->destroy(service->backend);
    service->backend = NULL;
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                            "PAPPL startup reconciliation failed");
  }
  service->state = HPLJ_SERVICE_READY;
  return hplj_pappl_error(HPLJ_ERROR_NONE, "PAPPL service ready");
}

bool hplj_service_is_ready(const struct hplj_service *service) {
  return service != NULL && service->state == HPLJ_SERVICE_READY;
}

struct hplj_error hplj_service_run(struct hplj_service *service) {
  if (!hplj_service_is_ready(service) || !service->ops.run(service->backend)) {
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE, "PAPPL service run failed");
  }
  service->state = HPLJ_SERVICE_STOPPED;
  return hplj_pappl_error(HPLJ_ERROR_NONE, "PAPPL service stopped");
}

void hplj_service_request_shutdown(struct hplj_service *service) {
  if (service != NULL && service->backend != NULL) {
    service->ops.shutdown(service->backend);
  }
}

struct hplj_error hplj_service_finish(struct hplj_service *service) {
  if (service == NULL || service->backend == NULL) {
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE, "PAPPL service is not prepared");
  }
  bool saved = service->ops.save_state(service->backend, service->state_path);
  service->ops.destroy(service->backend);
  service->backend = NULL;
  service->state = HPLJ_SERVICE_UNPREPARED;
  return saved ? hplj_pappl_error(HPLJ_ERROR_NONE, "PAPPL state saved")
               : hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                                   "could not save PAPPL state");
}

struct hplj_status hplj_status_from_device(enum hplj_device_state state) {
  switch (state) {
    case HPLJ_DEVICE_READY:
      return (struct hplj_status){.queue = HPLJ_QUEUE_READY,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = HPLJ_ERROR_NONE};
    case HPLJ_DEVICE_AWAITING_FIRMWARE:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_MISSING);
    case HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED);
    case HPLJ_DEVICE_FIRMWARE_UNVERIFIED:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_UNVERIFIED);
    case HPLJ_DEVICE_FIRMWARE_PRESENT:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = HPLJ_ERROR_FIRMWARE_UNVERIFIED};
    case HPLJ_DEVICE_DISCONNECTED:
    case HPLJ_DEVICE_PRE_FIRMWARE:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER};
    case HPLJ_DEVICE_UNSUPPORTED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_STOPPED,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER,
                                  .diagnostic = HPLJ_ERROR_UNSUPPORTED_DEVICE};
  }
  return (struct hplj_status){.queue = HPLJ_QUEUE_STOPPED, .action = HPLJ_ACTION_NONE};
}

struct hplj_status hplj_status_from_firmware_error(enum hplj_error_category category) {
  switch (category) {
    case HPLJ_ERROR_FIRMWARE_MISSING:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_IMPORT_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_AFFIRM_LAWFUL_ACQUISITION,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_UNSUPPORTED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_SELECT_SUPPORTED_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_CORRUPT:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_REACQUIRE_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RECONNECT_AND_RETRY_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_UNVERIFIED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_POWER_CYCLE_PRINTER,
                                  .diagnostic = category};
    default:
      return (struct hplj_status){.queue = HPLJ_QUEUE_STOPPED,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = category};
  }
}

void hplj_pappl_publish_status(const struct hplj_service_config *config,
                               const struct hplj_observer *observer,
                               hplj_pappl_publish_callback publish, void *context,
                               enum hplj_device_state device_state) {
  struct hplj_status status = hplj_status_from_device(device_state);
  if (config == NULL || config->queue_name == NULL || config->loopback_host == NULL ||
      config->ipp_port != 8631 || publish == NULL) {
    if (observer != NULL && observer->report != NULL) {
      observer->report(observer->context, "pappl",
                       hplj_error_make(HPLJ_ERROR_INVALID_STATE, HPLJ_RETRY_NEVER,
                                       HPLJ_ACTION_NONE, "invalid service configuration"));
    }
    return;
  }
  publish(context, status);
}
