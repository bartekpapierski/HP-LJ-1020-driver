// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_ENCODER_H
#define HPLJ_ENCODER_H

#include "hplj/error.h"

#include <stdbool.h>
#include <stddef.h>

enum hplj_bit_polarity { HPLJ_BLACK_IS_ONE, HPLJ_BLACK_IS_ZERO };
enum hplj_media { HPLJ_MEDIA_A4, HPLJ_MEDIA_LETTER };
enum hplj_source { HPLJ_SOURCE_AUTO, HPLJ_SOURCE_MANUAL };
enum hplj_quality { HPLJ_QUALITY_DRAFT, HPLJ_QUALITY_NORMAL, HPLJ_QUALITY_HIGH };

struct hplj_raster {
  size_t width_pixels;
  size_t height_rows;
  unsigned int resolution_dpi;
  size_t row_stride_bytes;
  const unsigned char *bits;
  enum hplj_bit_polarity bit_polarity;
  unsigned int page_count;
  enum hplj_media media;
  enum hplj_source source;
  enum hplj_quality quality;
  unsigned int density;
};

struct hplj_encoder_sink {
  enum hplj_error_category (*emit)(void *context, const unsigned char *bytes,
                                   size_t byte_count);
  void *context;
};

/*
 * This is the production adaptation point for the pinned foo2zjs JBIG and
 * model-1 ZjStream implementation. It borrows raster, sink, and context for
 * the call; it must not retain page data after returning.
 */
struct hplj_foo2zjs_adapter {
  enum hplj_error_category (*encode_zjstream)(
      void *context, const struct hplj_raster *raster, const struct hplj_encoder_sink *sink,
      bool cancelled, size_t *bytes_emitted);
  void *context;
};

struct hplj_encode_result {
  struct hplj_error error;
  size_t bytes_emitted;
};

struct hplj_encode_result hplj_encode_raster(const struct hplj_foo2zjs_adapter *encoder,
                                             const struct hplj_raster *raster,
                                             const struct hplj_encoder_sink *sink,
                                             bool cancelled);

#endif
