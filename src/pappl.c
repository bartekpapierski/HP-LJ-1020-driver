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
         ops->configure_policy != NULL &&
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
      !ops->load_state(service->backend, config->paths.state_path)) {
    ops->destroy(service->backend);
    service->backend = NULL;
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                            "PAPPL startup reconciliation failed");
  }
  if (!ops->reconcile_queue(service->backend, HPLJ_QUEUE_NAME,
                            HPLJ_DRIVER_NAME, config->device_uri)) {
    ops->destroy(service->backend);
    service->backend = NULL;
    return hplj_error_make(HPLJ_ERROR_QUEUE_UNAVAILABLE, HPLJ_RETRY_EXPLICIT,
                           HPLJ_ACTION_RETRY_QUEUE,
                           "print queue reconciliation failed");
  }
  const struct hplj_retention_policy policy = {
      .maximum_completed_jobs = HPLJ_MAX_COMPLETED_JOBS,
      .maximum_log_bytes = HPLJ_MAX_LOG_BYTES,
      .maximum_log_age_seconds = HPLJ_MAX_LOG_AGE_SECONDS,
  };
  if (!ops->configure_policy(service->backend, &policy)) {
    ops->destroy(service->backend);
    service->backend = NULL;
    return hplj_pappl_error(HPLJ_ERROR_INVALID_STATE,
                            "retention policy configuration failed");
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
      return (struct hplj_status){.code = HPLJ_STATUS_READY,
                                  .queue = HPLJ_QUEUE_READY,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = HPLJ_ERROR_NONE};
    case HPLJ_DEVICE_AWAITING_FIRMWARE:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_MISSING);
    case HPLJ_DEVICE_FIRMWARE_TRANSFER_FAILED:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED);
    case HPLJ_DEVICE_FIRMWARE_UNVERIFIED:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_UNVERIFIED);
    case HPLJ_DEVICE_FIRMWARE_PRESENT:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = HPLJ_ERROR_FIRMWARE_UNVERIFIED};
    case HPLJ_DEVICE_PRE_FIRMWARE:
      return hplj_status_from_firmware_error(HPLJ_ERROR_FIRMWARE_MISSING);
    case HPLJ_DEVICE_DISCONNECTED:
      return (struct hplj_status){.code = HPLJ_STATUS_DEVICE_DISCONNECTED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER,
                                  .diagnostic = HPLJ_ERROR_DEVICE_DISCONNECTED};
    case HPLJ_DEVICE_UNSUPPORTED:
      return (struct hplj_status){.code = HPLJ_STATUS_DEVICE_FAULT,
                                  .queue = HPLJ_QUEUE_STOPPED,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER,
                                  .diagnostic = HPLJ_ERROR_UNSUPPORTED_DEVICE};
  }
  return (struct hplj_status){.code = HPLJ_STATUS_DEVICE_FAULT,
                              .queue = HPLJ_QUEUE_STOPPED,
                              .action = HPLJ_ACTION_NONE};
}

struct hplj_status hplj_status_from_firmware_error(enum hplj_error_category category) {
  switch (category) {
    case HPLJ_ERROR_FIRMWARE_MISSING:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_REQUIRED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_IMPORT_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_REQUIRED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_AFFIRM_LAWFUL_ACQUISITION,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_UNSUPPORTED:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_SELECT_SUPPORTED_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_CORRUPT:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_REACQUIRE_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_STORAGE_FAILED:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RETRY_FIRMWARE_IMPORT,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RECONNECT_AND_RETRY_FIRMWARE,
                                  .diagnostic = category};
    case HPLJ_ERROR_FIRMWARE_UNVERIFIED:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_POWER_CYCLE_PRINTER,
                                  .diagnostic = category};
    default:
      return (struct hplj_status){.code = HPLJ_STATUS_FIRMWARE_FAILED,
                                  .queue = HPLJ_QUEUE_STOPPED,
                                  .action = HPLJ_ACTION_NONE,
                                  .diagnostic = category};
  }
}

struct hplj_status hplj_status_from_error(struct hplj_error error) {
  switch (error.category) {
    case HPLJ_ERROR_NONE:
      return hplj_status_from_device(HPLJ_DEVICE_READY);
    case HPLJ_ERROR_FIRMWARE_MISSING:
    case HPLJ_ERROR_FIRMWARE_AFFIRMATION_REQUIRED:
    case HPLJ_ERROR_FIRMWARE_UNSUPPORTED:
    case HPLJ_ERROR_FIRMWARE_CORRUPT:
    case HPLJ_ERROR_FIRMWARE_STORAGE_FAILED:
    case HPLJ_ERROR_FIRMWARE_TRANSFER_FAILED:
    case HPLJ_ERROR_FIRMWARE_UNVERIFIED:
      return hplj_status_from_firmware_error(error.category);
    case HPLJ_ERROR_DEVICE_DISCONNECTED:
      return (struct hplj_status){HPLJ_STATUS_DEVICE_DISCONNECTED,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_ERROR_RASTER_INVALID:
      return (struct hplj_status){HPLJ_STATUS_RASTER_INVALID,
                                  HPLJ_QUEUE_STOPPED, error.action,
                                  error.category};
    case HPLJ_ERROR_ENCODING_FAILED:
      return (struct hplj_status){HPLJ_STATUS_ENCODING_FAILED,
                                  HPLJ_QUEUE_STOPPED, error.action,
                                  error.category};
    case HPLJ_ERROR_TRANSFER_INCOMPLETE:
    case HPLJ_ERROR_DEVICE_TIMEOUT:
      return (struct hplj_status){HPLJ_STATUS_TRANSFER_FAILED,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_ERROR_QUEUE_UNAVAILABLE:
      return (struct hplj_status){HPLJ_STATUS_QUEUE_UNAVAILABLE,
                                  HPLJ_QUEUE_STOPPED, error.action,
                                  error.category};
    case HPLJ_ERROR_MEDIA_EMPTY:
      return (struct hplj_status){HPLJ_STATUS_MEDIA_EMPTY,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_ERROR_MANUAL_FEED_REQUIRED:
      return (struct hplj_status){HPLJ_STATUS_MANUAL_FEED,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_ERROR_COVER_OPEN:
      return (struct hplj_status){HPLJ_STATUS_COVER_OPEN,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_ERROR_CANCELLED:
      return (struct hplj_status){HPLJ_STATUS_CANCELED,
                                  HPLJ_QUEUE_READY, error.action,
                                  error.category};
    default:
      return (struct hplj_status){HPLJ_STATUS_DEVICE_FAULT,
                                  HPLJ_QUEUE_STOPPED, error.action,
                                  error.category};
  }
}

struct hplj_status hplj_status_from_conditions(unsigned int conditions) {
  return hplj_status_from_error(hplj_error_from_conditions(conditions));
}

struct hplj_status hplj_status_from_job(enum hplj_job_state state,
                                        struct hplj_error error) {
  switch (state) {
    case HPLJ_JOB_ACCEPTED:
      return (struct hplj_status){HPLJ_STATUS_JOB_ACCEPTED,
                                  HPLJ_QUEUE_READY, HPLJ_ACTION_NONE,
                                  HPLJ_ERROR_NONE};
    case HPLJ_JOB_HELD_FOR_FIRMWARE:
      return (struct hplj_status){HPLJ_STATUS_JOB_HELD_FOR_FIRMWARE,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_JOB_HELD_FOR_DEVICE:
      return (struct hplj_status){HPLJ_STATUS_JOB_HELD_FOR_DEVICE,
                                  HPLJ_QUEUE_HELD, error.action,
                                  error.category};
    case HPLJ_JOB_PREPARING:
      return (struct hplj_status){HPLJ_STATUS_JOB_PREPARING,
                                  HPLJ_QUEUE_READY, HPLJ_ACTION_NONE,
                                  HPLJ_ERROR_NONE};
    case HPLJ_JOB_TRANSMITTING:
      return (struct hplj_status){HPLJ_STATUS_JOB_TRANSMITTING,
                                  HPLJ_QUEUE_READY, HPLJ_ACTION_NONE,
                                  HPLJ_ERROR_NONE};
    case HPLJ_JOB_WAITING_FOR_MEDIA:
      return hplj_status_from_error(error);
    case HPLJ_JOB_COMPLETED:
      return (struct hplj_status){HPLJ_STATUS_JOB_COMPLETED,
                                  HPLJ_QUEUE_READY, HPLJ_ACTION_NONE,
                                  HPLJ_ERROR_NONE};
    case HPLJ_JOB_CANCELED:
    case HPLJ_JOB_FAILED:
    case HPLJ_JOB_FAILED_PARTIAL:
      return hplj_status_from_error(error);
  }
  return hplj_status_from_error(error);
}

const char *hplj_status_name(enum hplj_user_status status) {
  switch (status) {
    case HPLJ_STATUS_READY:
      return "ready";
    case HPLJ_STATUS_JOB_ACCEPTED:
      return "job-accepted";
    case HPLJ_STATUS_JOB_HELD_FOR_FIRMWARE:
      return "job-held-for-firmware";
    case HPLJ_STATUS_JOB_HELD_FOR_DEVICE:
      return "job-held-for-device";
    case HPLJ_STATUS_JOB_PREPARING:
      return "job-preparing";
    case HPLJ_STATUS_JOB_TRANSMITTING:
      return "job-transmitting";
    case HPLJ_STATUS_JOB_COMPLETED:
      return "job-completed";
    case HPLJ_STATUS_DEVICE_DISCONNECTED:
      return "device-disconnected";
    case HPLJ_STATUS_DEVICE_FAULT:
      return "device-fault";
    case HPLJ_STATUS_FIRMWARE_REQUIRED:
      return "firmware-required";
    case HPLJ_STATUS_FIRMWARE_FAILED:
      return "firmware-failed";
    case HPLJ_STATUS_QUEUE_UNAVAILABLE:
      return "queue-unavailable";
    case HPLJ_STATUS_RASTER_INVALID:
      return "raster-invalid";
    case HPLJ_STATUS_ENCODING_FAILED:
      return "encoding-failed";
    case HPLJ_STATUS_TRANSFER_FAILED:
      return "transfer-failed";
    case HPLJ_STATUS_MEDIA_EMPTY:
      return "media-empty";
    case HPLJ_STATUS_MANUAL_FEED:
      return "manual-feed";
    case HPLJ_STATUS_COVER_OPEN:
      return "cover-open";
    case HPLJ_STATUS_CANCELED:
      return "canceled";
  }
  return "device-fault";
}

bool hplj_log_rotation_due(size_t bytes, unsigned long long created_at,
                            unsigned long long now,
                            const struct hplj_retention_policy *policy) {
  if (policy == NULL) {
    return false;
  }
  if (policy->maximum_log_bytes > 0 &&
      bytes >= policy->maximum_log_bytes) {
    return true;
  }
  return policy->maximum_log_age_seconds > 0 && now >= created_at &&
         now - created_at >= policy->maximum_log_age_seconds;
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
