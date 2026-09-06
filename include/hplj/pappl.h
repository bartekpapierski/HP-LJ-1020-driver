// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_PAPPL_H
#define HPLJ_PAPPL_H

#include "hplj/config.h"
#include "hplj/device.h"
#include "hplj/encoder.h"

#include <stdbool.h>

#define HPLJ_QUEUE_NAME "HP_LaserJet_1020"
#define HPLJ_DRIVER_NAME "hp_laserjet_1020"
#define HPLJ_IPV4_LOOPBACK "127.0.0.1"
#define HPLJ_IPV6_LOOPBACK "[::1]"
#define HPLJ_IPP_PORT 8631U

enum hplj_queue_state { HPLJ_QUEUE_READY, HPLJ_QUEUE_HELD, HPLJ_QUEUE_STOPPED };

struct hplj_status {
  enum hplj_queue_state queue;
  enum hplj_human_action action;
  enum hplj_error_category diagnostic;
};

struct hplj_capabilities {
  unsigned int raster_resolution_dpi;
  enum hplj_media media;
  enum hplj_source source;
  enum hplj_quality quality;
  unsigned int density;
};

enum hplj_document_format {
  HPLJ_DOCUMENT_PWG_RASTER,
  HPLJ_DOCUMENT_APPLE_RASTER,
  HPLJ_DOCUMENT_PDF,
  HPLJ_DOCUMENT_UNKNOWN,
};

struct hplj_job_attributes {
  enum hplj_document_format format;
  unsigned int resolution_dpi;
  unsigned int bits_per_pixel;
  enum hplj_media media;
  enum hplj_source source;
  enum hplj_quality quality;
  unsigned int density;
};

struct hplj_capability_profile {
  unsigned int resolution_dpi;
  unsigned int bits_per_pixel;
  enum hplj_source source;
  enum hplj_quality quality;
  unsigned int density;
};

enum hplj_service_state {
  HPLJ_SERVICE_UNPREPARED,
  HPLJ_SERVICE_READY,
  HPLJ_SERVICE_STOPPED,
};

/*
 * PAPPL lifecycle calls are isolated behind this interface so host tests can
 * prove binding, state, reconciliation, readiness, and shutdown policy without
 * opening sockets or requiring a printer.
 */
struct hplj_service_ops {
  void *(*create)(void *context, const struct hplj_service_config *config);
  bool (*add_listener)(void *service, const char *address);
  bool (*load_state)(void *service, const char *path);
  bool (*reconcile_queue)(void *service, const char *queue_name,
                          const char *driver_name, const char *device_uri);
  bool (*run)(void *service);
  void (*shutdown)(void *service);
  bool (*save_state)(void *service, const char *path);
  void (*destroy)(void *service);
  void *context;
};

struct hplj_service {
  struct hplj_service_ops ops;
  void *backend;
  const char *state_path;
  enum hplj_service_state state;
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
struct hplj_status hplj_status_from_firmware_error(enum hplj_error_category category);
void hplj_pappl_publish_status(const struct hplj_service_config *config,
                               const struct hplj_observer *observer,
                               hplj_pappl_publish_callback publish, void *context,
                               enum hplj_device_state device_state);
struct hplj_error hplj_pappl_validate_job(const struct hplj_job_attributes *job);
const struct hplj_capability_profile *hplj_pappl_capabilities(void);
struct hplj_error hplj_service_prepare(struct hplj_service *service,
                                       const struct hplj_service_config *config,
                                       const struct hplj_service_ops *ops);
bool hplj_service_is_ready(const struct hplj_service *service);
struct hplj_error hplj_service_run(struct hplj_service *service);
void hplj_service_request_shutdown(struct hplj_service *service);
struct hplj_error hplj_service_finish(struct hplj_service *service);
int hplj_pappl_serve(const struct hplj_service_config *config);

#endif
