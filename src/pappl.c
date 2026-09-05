// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"

struct hplj_status hplj_status_from_device(enum hplj_device_state state) {
  switch (state) {
    case HPLJ_DEVICE_READY:
      return (struct hplj_status){.queue = HPLJ_QUEUE_READY, .action = HPLJ_ACTION_NONE};
    case HPLJ_DEVICE_AWAITING_FIRMWARE:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_IMPORT_FIRMWARE};
    case HPLJ_DEVICE_DISCONNECTED:
    case HPLJ_DEVICE_PRE_FIRMWARE:
      return (struct hplj_status){.queue = HPLJ_QUEUE_HELD,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER};
    case HPLJ_DEVICE_UNSUPPORTED:
      return (struct hplj_status){.queue = HPLJ_QUEUE_STOPPED,
                                  .action = HPLJ_ACTION_RECONNECT_PRINTER};
  }
  return (struct hplj_status){.queue = HPLJ_QUEUE_STOPPED, .action = HPLJ_ACTION_NONE};
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
