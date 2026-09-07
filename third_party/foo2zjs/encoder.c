// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Adapted from OpenPrinting/foo2zjs foo2zjs.c at commit
 * 80499ed5bf6caa2963ad337e37cfda78a80aab1e.
 *
 * This program began as Robert Szalai's pbmtozjs, uses Markus Kuhn's bundled
 * JBIG-KIT compression library, and was overhauled by Rick Richardson.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version. This program is distributed without any warranty; see
 * the GNU General Public License for details.
 *
 * Modified by HP-LJ-1020-driver contributors, 2026-09-07.
 */
#include "hplj/encoder.h"

#include "jbig.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum {
  ZJT_START_DOC = 0,
  ZJT_END_DOC = 1,
  ZJT_START_PAGE = 2,
  ZJT_END_PAGE = 3,
  ZJT_JBIG_BIH = 4,
  ZJT_JBIG_BID = 5,
  ZJT_END_JBIG = 6,
  ZJI_PAGECOUNT = 0,
  ZJI_DMCOLLATE = 1,
  ZJI_DMDUPLEX = 2,
  ZJI_DMPAPER = 3,
  ZJI_DMCOPIES = 4,
  ZJI_DMDEFAULTSOURCE = 5,
  ZJI_DMMEDIATYPE = 6,
  ZJI_NBIE = 7,
  ZJI_RESOLUTION_X = 8,
  ZJI_RESOLUTION_Y = 9,
  ZJI_RASTER_X = 12,
  ZJI_RASTER_Y = 13,
  ZJI_VIDEO_BPP = 16,
  ZJI_VIDEO_X = 17,
  ZJI_VIDEO_Y = 18,
  ZJI_ECONOMODE = 23,
  ZJIT_UINT32 = 1,
  DMDUPLEX_OFF = 1,
  DMBIN_AUTO = 7,
  DMMEDIA_STANDARD = 1,
  DMPAPER_LETTER = 1,
  DMPAPER_A4 = 9,
  MODEL_1_START_DOC_RESERVED = 0x24,
  MODEL_1_START_PAGE_RESERVED = 0x9c,
  MODEL_1_JBIG_CHUNK = 65536,
  MODEL_1_END_PADDING = 16,
};

struct byte_buffer {
  unsigned char *bytes;
  size_t size;
  size_t capacity;
  bool failed;
};

static bool append_bytes(struct byte_buffer *buffer, const void *bytes,
                         size_t byte_count) {
  if (buffer->failed || byte_count > SIZE_MAX - buffer->size) {
    buffer->failed = true;
    return false;
  }
  const size_t required = buffer->size + byte_count;
  if (required > buffer->capacity) {
    size_t capacity = buffer->capacity == 0 ? 1024 : buffer->capacity;
    while (capacity < required) {
      if (capacity > SIZE_MAX / 2) {
        capacity = required;
        break;
      }
      capacity *= 2;
    }
    unsigned char *grown = realloc(buffer->bytes, capacity);
    if (grown == NULL) {
      buffer->failed = true;
      return false;
    }
    buffer->bytes = grown;
    buffer->capacity = capacity;
  }
  memcpy(buffer->bytes + buffer->size, bytes, byte_count);
  buffer->size = required;
  return true;
}

static bool append_u8(struct byte_buffer *buffer, unsigned int value) {
  const unsigned char byte = (unsigned char)value;
  return append_bytes(buffer, &byte, 1);
}

static bool append_be16(struct byte_buffer *buffer, uint16_t value) {
  const unsigned char bytes[] = {(unsigned char)(value >> 8U),
                                 (unsigned char)value};
  return append_bytes(buffer, bytes, sizeof(bytes));
}

static bool append_be32(struct byte_buffer *buffer, uint32_t value) {
  const unsigned char bytes[] = {
      (unsigned char)(value >> 24U), (unsigned char)(value >> 16U),
      (unsigned char)(value >> 8U), (unsigned char)value};
  return append_bytes(buffer, bytes, sizeof(bytes));
}

static bool append_chunk(struct byte_buffer *buffer, uint32_t type,
                         uint16_t reserved, uint32_t items,
                         uint32_t payload_size) {
  return append_be32(buffer, 16U + payload_size) && append_be32(buffer, type) &&
         append_be32(buffer, items) && append_be16(buffer, reserved) &&
         append_bytes(buffer, "ZZ", 2);
}

static bool append_item(struct byte_buffer *buffer, uint16_t item,
                        uint32_t value) {
  return append_be32(buffer, 12) && append_be16(buffer, item) &&
         append_u8(buffer, ZJIT_UINT32) && append_u8(buffer, 0) &&
         append_be32(buffer, value);
}

static uint32_t read_be32(const unsigned char *bytes) {
  return ((uint32_t)bytes[0] << 24U) | ((uint32_t)bytes[1] << 16U) |
         ((uint32_t)bytes[2] << 8U) | (uint32_t)bytes[3];
}

static void capture_jbig(unsigned char *bytes, size_t byte_count, void *context) {
  (void)append_bytes(context, bytes, byte_count);
}

static bool append_start_document(struct byte_buffer *stream) {
  static const char prefix[] =
      "\033%-12345X@PJL JOB\n"
      "@PJL SET JAMRECOVERY=OFF\n"
      "@PJL SET DENSITY=3\n"
      "@PJL SET ECONOMODE=OFF\n"
      "@PJL SET RET=MEDIUM\n"
      "@PJL INFO STATUS\n"
      "@PJL USTATUS DEVICE = ON\n"
      "@PJL USTATUS JOB = ON\n"
      "@PJL USTATUS PAGE = ON\n"
      "@PJL USTATUS TIMED = 30\n"
      "@PJL SET JOBATTR=\"JobAttr4=";
  static const char suffix[] = "\"";
  static const char enter_zjstream[] = "\033%-12345XJZJZ";
  static const char timestamp[] = "00000000000000";
  return append_bytes(stream, prefix, sizeof(prefix) - 1) &&
         append_bytes(stream, timestamp, 14) &&
         append_bytes(stream, suffix, sizeof(suffix) - 1) && append_u8(stream, 0) &&
         append_bytes(stream, enter_zjstream, sizeof(enter_zjstream) - 1) &&
         append_chunk(stream, ZJT_START_DOC, MODEL_1_START_DOC_RESERVED, 3, 36) &&
         append_item(stream, ZJI_DMCOLLATE, 0) &&
         append_item(stream, ZJI_DMDUPLEX, DMDUPLEX_OFF) &&
         append_item(stream, ZJI_PAGECOUNT, 0);
}

static bool append_start_page(struct byte_buffer *stream,
                              const struct hplj_raster *raster) {
  const uint32_t paper = raster->media == HPLJ_MEDIA_LETTER ? DMPAPER_LETTER
                                                            : DMPAPER_A4;
  return append_chunk(stream, ZJT_START_PAGE, MODEL_1_START_PAGE_RESERVED, 13,
                      13 * 12) &&
         append_item(stream, ZJI_ECONOMODE, 0) &&
         append_item(stream, ZJI_VIDEO_X,
                     (uint32_t)raster->printable_width_pixels) &&
         append_item(stream, ZJI_VIDEO_Y,
                     (uint32_t)raster->printable_height_rows) &&
         append_item(stream, ZJI_VIDEO_BPP, 1) &&
         append_item(stream, ZJI_RASTER_X,
                     (uint32_t)raster->printable_width_pixels) &&
         append_item(stream, ZJI_RASTER_Y,
                     (uint32_t)raster->printable_height_rows) &&
         append_item(stream, ZJI_NBIE, 1) &&
         append_item(stream, ZJI_RESOLUTION_X, 600) &&
         append_item(stream, ZJI_RESOLUTION_Y, 600) &&
         append_item(stream, ZJI_DMDEFAULTSOURCE, DMBIN_AUTO) &&
         append_item(stream, ZJI_DMCOPIES, 1) &&
         append_item(stream, ZJI_DMPAPER, paper) &&
         append_item(stream, ZJI_DMMEDIATYPE, DMMEDIA_STANDARD);
}

static bool append_jbig_records(struct byte_buffer *stream,
                                const struct byte_buffer *jbig) {
  if (jbig->failed || jbig->size <= 20 ||
      !append_chunk(stream, ZJT_JBIG_BIH, 0, 0, 20) ||
      !append_bytes(stream, jbig->bytes, 20)) {
    return false;
  }
  size_t offset = 20;
  while (offset < jbig->size) {
    size_t byte_count = jbig->size - offset;
    if (byte_count > MODEL_1_JBIG_CHUNK) {
      byte_count = MODEL_1_JBIG_CHUNK;
    }
    size_t padding = 0;
    if (offset + byte_count == jbig->size) {
      padding = MODEL_1_END_PADDING + (4 - (byte_count % 4)) % 4;
    }
    if (byte_count + padding > UINT32_MAX ||
        !append_chunk(stream, ZJT_JBIG_BID, 0, 0,
                      (uint32_t)(byte_count + padding)) ||
        !append_bytes(stream, jbig->bytes + offset, byte_count)) {
      return false;
    }
    for (size_t i = 0; i < padding; ++i) {
      if (!append_u8(stream, 0)) {
        return false;
      }
    }
    offset += byte_count;
  }
  return append_chunk(stream, ZJT_END_JBIG, 0, 0, 0);
}

static bool normalized_page(const struct hplj_raster *raster,
                            unsigned int page, uint32_t padded_width,
                            struct byte_buffer *normalized) {
  const size_t output_stride = padded_width / 8U;
  const size_t page_input_size = raster->row_stride_bytes * raster->height_rows;
  const unsigned char *page_bits = raster->bits + page * page_input_size;
  const size_t output_size = output_stride * raster->printable_height_rows;
  normalized->bytes = calloc(output_size, 1);
  if (normalized->bytes == NULL) {
    normalized->failed = true;
    return false;
  }
  normalized->size = output_size;
  normalized->capacity = output_size;
  for (size_t y = 0; y < raster->printable_height_rows; ++y) {
    const unsigned char *source =
        page_bits + (raster->printable_y_rows + y) * raster->row_stride_bytes;
    unsigned char *destination = normalized->bytes + y * output_stride;
    for (size_t x = 0; x < raster->printable_width_pixels; ++x) {
      const size_t source_x = raster->printable_x_pixels + x;
      const unsigned int source_shift =
          raster->bit_order == HPLJ_MOST_SIGNIFICANT_BIT_FIRST
              ? 7U - (unsigned int)(source_x % 8U)
              : (unsigned int)(source_x % 8U);
      const bool set = (source[source_x / 8U] & (1U << source_shift)) != 0;
      const bool black = raster->bit_polarity == HPLJ_BLACK_IS_ONE ? set : !set;
      if (black) {
        destination[x / 8U] |= (unsigned char)(1U << (7U - (unsigned int)(x % 8U)));
      }
    }
  }
  return true;
}

static bool append_page(struct byte_buffer *stream,
                        const struct hplj_raster *raster, unsigned int page) {
  const uint32_t printable_width = (uint32_t)raster->printable_width_pixels;
  const uint32_t padded_width = (printable_width + 127U) & ~127U;
  struct byte_buffer normalized = {0};
  struct byte_buffer jbig = {0};
  if (!normalized_page(raster, page, padded_width, &normalized)) {
    return false;
  }
  unsigned char *planes[] = {normalized.bytes};
  struct jbg_enc_state encoder;
  jbg_enc_init(&encoder, padded_width, raster->printable_height_rows, 1, planes,
               capture_jbig, &jbig);
  jbg_enc_options(&encoder, JBG_ILEAVE | JBG_SMID,
                  JBG_DELAY_AT | JBG_LRLTWO | JBG_TPDON | JBG_TPBON | JBG_DPON,
                  128, 0, 0);
  jbg_enc_out(&encoder);
  jbg_enc_free(&encoder);
  free(normalized.bytes);

  const bool ok = append_start_page(stream, raster) &&
                  append_jbig_records(stream, &jbig) &&
                  append_chunk(stream, ZJT_END_PAGE, 0, 0, 0);
  free(jbig.bytes);
  return ok;
}

static bool append_end_document(struct byte_buffer *stream) {
  static const char trailer[] = "\033%-12345X@PJL EOJ\n\033%-12345X";
  return append_chunk(stream, ZJT_END_DOC, 0, 0, 0) &&
         append_bytes(stream, trailer, sizeof(trailer) - 1);
}

static bool structurally_valid(const struct byte_buffer *stream,
                               unsigned int expected_pages) {
  static const unsigned char magic[] = {'J', 'Z', 'J', 'Z'};
  const unsigned char *begin = NULL;
  for (size_t i = 0; i + sizeof(magic) <= stream->size; ++i) {
    if (memcmp(stream->bytes + i, magic, sizeof(magic)) == 0) {
      begin = stream->bytes + i + sizeof(magic);
      break;
    }
  }
  if (begin == NULL) {
    return false;
  }
  const unsigned char *cursor = begin;
  const unsigned char *end = stream->bytes + stream->size;
  unsigned int pages = 0;
  uint32_t previous = UINT32_MAX;
  while (cursor + 16 <= end) {
    const uint32_t size = read_be32(cursor);
    const uint32_t type = read_be32(cursor + 4);
    if (size < 16 || size > (size_t)(end - cursor) || cursor[14] != 'Z' ||
        cursor[15] != 'Z') {
      return false;
    }
    if ((previous == UINT32_MAX && type != ZJT_START_DOC) ||
        (type == ZJT_START_PAGE && previous != ZJT_START_DOC && previous != ZJT_END_PAGE) ||
        (type == ZJT_JBIG_BIH && previous != ZJT_START_PAGE) ||
        (type == ZJT_JBIG_BID && previous != ZJT_JBIG_BIH && previous != ZJT_JBIG_BID) ||
        (type == ZJT_END_JBIG && previous != ZJT_JBIG_BID) ||
        (type == ZJT_END_PAGE && previous != ZJT_END_JBIG) ||
        (type == ZJT_END_DOC && previous != ZJT_END_PAGE)) {
      return false;
    }
    if (type == ZJT_START_PAGE) {
      ++pages;
    }
    cursor += size;
    previous = type;
    if (type == ZJT_END_DOC) {
      return pages == expected_pages;
    }
  }
  return false;
}

static enum hplj_error_category encode_model_1(
    void *context, const struct hplj_raster *raster,
    const struct hplj_encoder_sink *sink, bool cancelled,
    size_t *bytes_emitted) {
  (void)context;
  *bytes_emitted = 0;
  if (cancelled) {
    return HPLJ_ERROR_CANCELLED;
  }
  struct byte_buffer stream = {0};
  bool ok = append_start_document(&stream);
  for (unsigned int page = 0; ok && page < raster->page_count; ++page) {
    ok = append_page(&stream, raster, page);
  }
  ok = ok && append_end_document(&stream) &&
       structurally_valid(&stream, raster->page_count);
  if (!ok || stream.failed) {
    free(stream.bytes);
    return HPLJ_ERROR_ENCODING_FAILED;
  }
  const enum hplj_error_category result =
      sink->emit(sink->context, stream.bytes, stream.size);
  if (result == HPLJ_ERROR_NONE) {
    *bytes_emitted = stream.size;
  }
  free(stream.bytes);
  return result;
}

const struct hplj_foo2zjs_adapter *hplj_foo2zjs_model_1(void) {
  static const struct hplj_foo2zjs_adapter adapter = {
      .encode_zjstream = encode_model_1,
      .context = NULL,
  };
  return &adapter;
}
