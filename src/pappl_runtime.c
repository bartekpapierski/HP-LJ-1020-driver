// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/pappl.h"
#include "hplj/job.h"

#include <pappl/pappl.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if CUPS_VERSION_MAJOR < 3
#define cups_page_header_t cups_page_header2_t
#endif

struct hplj_pappl_backend {
  pappl_system_t *system;
};

struct hplj_queue_lookup {
  const char *name;
  pappl_printer_t *printer;
};

struct hplj_pappl_job_data {
  unsigned char *page_bits;
  size_t page_size;
  unsigned int rows_received;
  struct hplj_device transport;
  struct hplj_job lifecycle;
  pappl_device_t *pappl_device;
};

static void hplj_free_job_data(struct hplj_pappl_job_data *data) {
  if (data != NULL) {
    free(data->page_bits);
    free(data);
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
  static const char *messages[] = {
      "accepted",         "held-for-firmware", "preparing", "transmitting",
      "completed",        "canceled",          "failed",
  };
  if ((size_t)metadata->state < sizeof(messages) / sizeof(messages[0])) {
    papplJobSetMessage(job, "%s", messages[metadata->state]);
  }
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
  data->pappl_device = device;
  struct hplj_device_ops ops = {
      .write = hplj_pappl_write,
      .context = data,
  };
  hplj_device_init(&data->transport, &ops);
  data->transport.state = HPLJ_DEVICE_READY;
  papplCopyString(data->transport.firmware_version, "pappl-managed",
                  sizeof(data->transport.firmware_version));
  hplj_job_init(&data->lifecycle, (unsigned long)papplJobGetID(job),
                &data->transport, hplj_foo2zjs_model_1(),
                hplj_pappl_job_cancelled, hplj_pappl_job_state, job);
  papplJobSetData(job, data);
  if (papplJobIsCanceled(job)) {
    hplj_free_job_data(data);
    papplJobSetData(job, NULL);
    return false;
  }
  struct hplj_error error =
      hplj_job_prepare(&data->lifecycle, NULL, 0, "pappl-managed");
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
  const struct hplj_error result =
      hplj_job_submit_page(&data->lifecycle, &raster);
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
  backend->system = papplSystemCreate(
      PAPPL_SOPTIONS_NO_TLS, "HP LaserJet 1020", config->ipp_port, NULL,
      config->paths.spool_path, config->paths.log_path, PAPPL_LOGLEVEL_INFO,
      NULL, false);
  if (backend->system == NULL) {
    free(backend);
    return NULL;
  }
  static pappl_pr_driver_t drivers[] = {
      {HPLJ_DRIVER_NAME, "HP LaserJet 1020", "MFG:HP;MDL:HP LaserJet 1020;", NULL},
  };
  papplSystemSetDNSSDName(backend->system, NULL);
  papplSystemSetMaxLogSize(backend->system, 1024 * 1024);
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
  struct hplj_queue_lookup lookup = {.name = queue_name, .printer = NULL};
  papplSystemIteratePrinters(backend->system, hplj_find_queue, &lookup);
  if (lookup.printer != NULL) {
    return strcmp(papplPrinterGetDriverName(lookup.printer), driver_name) == 0 &&
           strcmp(papplPrinterGetDeviceURI(lookup.printer), device_uri) == 0;
  }
  pappl_printer_t *printer = papplPrinterCreate(
      backend->system, 0, queue_name, driver_name,
      "MFG:HP;MDL:HP LaserJet 1020;", device_uri);
  if (printer == NULL) {
    return false;
  }
  papplPrinterSetDNSSDName(printer, NULL);
  papplPrinterSetMaxCompletedJobs(printer, 0);
  papplPrinterSetMaxPreservedJobs(printer, 0);
  papplPrinterSetMaxActiveJobs(printer, 0);
  return true;
}

static bool hplj_backend_run(void *service) {
  struct hplj_pappl_backend *backend = service;
  papplSystemRun(backend->system);
  return true;
}

static void hplj_backend_shutdown(void *service) {
  struct hplj_pappl_backend *backend = service;
  papplSystemShutdown(backend->system);
}

static bool hplj_backend_save_state(void *service, const char *path) {
  struct hplj_pappl_backend *backend = service;
  return papplSystemSaveState(backend->system, path);
}

static void hplj_backend_destroy(void *service) {
  struct hplj_pappl_backend *backend = service;
  papplSystemDelete(backend->system);
  free(backend);
}

int hplj_pappl_serve(const struct hplj_service_config *config) {
  struct hplj_service service;
  struct hplj_service_ops ops = {
      .create = hplj_backend_create,
      .add_listener = hplj_backend_add_listener,
      .load_state = hplj_backend_load_state,
      .reconcile_queue = hplj_backend_reconcile,
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
  if (!papplSystemAddTimerCallback(backend->system, 0, 0, hplj_report_ready,
                                   NULL)) {
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
