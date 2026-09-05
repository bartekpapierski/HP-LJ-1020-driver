// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_PAPPL_H
#define HPLJ_PAPPL_H

#include "hplj/config.h"
#include "hplj/device.h"
#include "hplj/encoder.h"

enum hplj_queue_state { HPLJ_QUEUE_READY, HPLJ_QUEUE_HELD, HPLJ_QUEUE_STOPPED };

struct hplj_status {
  enum hplj_queue_state queue;
  enum hplj_human_action action;
};

struct hplj_capabilities {
  unsigned int raster_resolution_dpi;
  enum hplj_media media;
  enum hplj_source source;
  enum hplj_quality quality;
  unsigned int density;
};

/*
 * PAPPL integration is represented only by C-owned data and callbacks.
 * Driverless discovery, capability publication, raster negotiation, job
 * acceptance, cancellation, and status publication are independently
 * replaceable without exposing PAPPL types to the encoder or USB boundary.
 */
struct hplj_pappl_ops {
  enum hplj_error_category (*discover_driverless)(void *context);
  enum hplj_error_category (*publish_capabilities)(
      void *context, const struct hplj_capabilities *capabilities);
  enum hplj_error_category (*negotiate_raster)(void *context,
                                                const struct hplj_raster *raster);
  enum hplj_error_category (*accept_job)(void *context, unsigned long job_id);
  bool (*is_cancelled)(void *context, unsigned long job_id);
  void *context;
};

/*
 * The callback is a borrowed PAPPL-facing boundary. The adapter does not
 * retain the config, observer, or callback context after the call returns.
 */
typedef void (*hplj_pappl_publish_callback)(void *context, struct hplj_status status);

struct hplj_status hplj_status_from_device(enum hplj_device_state state);
void hplj_pappl_publish_status(const struct hplj_service_config *config,
                               const struct hplj_observer *observer,
                               hplj_pappl_publish_callback publish, void *context,
                               enum hplj_device_state device_state);

#endif
