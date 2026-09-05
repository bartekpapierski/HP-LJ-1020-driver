// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/encoder.h"

#include <stdint.h>

static struct hplj_encode_result hplj_encode_error(enum hplj_error_category category,
                                                    enum hplj_retry_safety retry,
                                                    enum hplj_human_action action,
                                                    const char *detail,
                                                    size_t bytes_emitted) {
  return (struct hplj_encode_result){
      .error = hplj_error_make(category, retry, action, detail),
      .bytes_emitted = bytes_emitted,
  };
}

struct hplj_encode_result hplj_encode_raster(const struct hplj_foo2zjs_adapter *encoder,
                                             const struct hplj_raster *raster,
                                             const struct hplj_encoder_sink *sink,
                                             bool cancelled) {
  if (cancelled) {
    return hplj_encode_error(HPLJ_ERROR_CANCELLED, HPLJ_RETRY_NEVER, HPLJ_ACTION_NONE,
                             "job was cancelled before encoding", 0);
  }
  if (encoder == NULL || encoder->encode_zjstream == NULL || raster == NULL || sink == NULL ||
      sink->emit == NULL || raster->bits == NULL ||
      raster->width_pixels == 0 || raster->height_rows == 0 || raster->page_count != 1 ||
      raster->resolution_dpi != 600 || raster->width_pixels > SIZE_MAX - 7 ||
      raster->row_stride_bytes < (raster->width_pixels + 7) / 8) {
    return hplj_encode_error(HPLJ_ERROR_RASTER_INVALID, HPLJ_RETRY_NEVER,
                             HPLJ_ACTION_CORRECT_RASTER, "raster geometry is unsupported", 0);
  }
  if (raster->height_rows > SIZE_MAX / raster->row_stride_bytes) {
    return hplj_encode_error(HPLJ_ERROR_RASTER_INVALID, HPLJ_RETRY_NEVER,
                             HPLJ_ACTION_CORRECT_RASTER, "raster size overflows", 0);
  }
  size_t bytes_emitted = 0;
  enum hplj_error_category category =
      encoder->encode_zjstream(encoder->context, raster, sink, cancelled, &bytes_emitted);
  if (category != HPLJ_ERROR_NONE) {
    enum hplj_retry_safety retry = bytes_emitted == 0 ? HPLJ_RETRY_SAFE_AUTOMATIC
                                                       : HPLJ_RETRY_EXPLICIT;
    return hplj_encode_error(category, retry, HPLJ_ACTION_RETRY_JOB,
                             "encoder output sink failed", bytes_emitted);
  }
  return (struct hplj_encode_result){
      .error = hplj_error_make(HPLJ_ERROR_NONE, HPLJ_RETRY_SAFE_AUTOMATIC,
                               HPLJ_ACTION_NONE, "encoded"),
      .bytes_emitted = bytes_emitted,
  };
}
