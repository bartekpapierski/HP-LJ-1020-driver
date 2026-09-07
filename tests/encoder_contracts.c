// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/encoder.h"

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum { OUTPUT_CAPACITY = 16384 };

struct capture {
  unsigned char bytes[OUTPUT_CAPACITY];
  size_t size;
  enum hplj_error_category failure;
};

static enum hplj_error_category capture_emit(void *context,
                                              const unsigned char *bytes,
                                              size_t byte_count) {
  struct capture *capture = context;
  if (capture->failure != HPLJ_ERROR_NONE) {
    return capture->failure;
  }
  assert(byte_count <= OUTPUT_CAPACITY - capture->size);
  memcpy(capture->bytes + capture->size, bytes, byte_count);
  capture->size += byte_count;
  return HPLJ_ERROR_NONE;
}

static struct hplj_raster tiny_raster(const unsigned char *bits) {
  return (struct hplj_raster){
      .width_pixels = 13,
      .height_rows = 2,
      .resolution_dpi = 600,
      .painted_resolution_dpi = 600,
      .page_width_pixels = 13,
      .page_height_rows = 2,
      .printable_x_pixels = 0,
      .printable_y_rows = 0,
      .printable_width_pixels = 13,
      .printable_height_rows = 2,
      .row_stride_bytes = 2,
      .bits = bits,
      .bits_size = 4,
      .bit_polarity = HPLJ_BLACK_IS_ONE,
      .bit_order = HPLJ_MOST_SIGNIFICANT_BIT_FIRST,
      .page_count = 1,
      .media = HPLJ_MEDIA_A4,
      .source = HPLJ_SOURCE_AUTO,
      .quality = HPLJ_QUALITY_NORMAL,
      .density = 3,
  };
}

struct fake_encoder {
  unsigned int calls;
  enum hplj_error_category result;
};

static enum hplj_error_category fake_encode(
    void *context, const struct hplj_raster *raster,
    const struct hplj_encoder_sink *sink, bool cancelled,
    size_t *bytes_emitted) {
  struct fake_encoder *encoder = context;
  (void)raster;
  (void)sink;
  (void)cancelled;
  encoder->calls++;
  *bytes_emitted = 0;
  return encoder->result;
}

static struct hplj_encode_result encode_with_fake(struct hplj_raster *raster,
                                                  struct fake_encoder *encoder,
                                                  bool cancelled) {
  struct capture capture = {0};
  return hplj_encode_raster(
      &(struct hplj_foo2zjs_adapter){.encode_zjstream = fake_encode,
                                     .context = encoder},
      raster, &(struct hplj_encoder_sink){.emit = capture_emit, .context = &capture},
      cancelled);
}

static uint32_t read_be32(const unsigned char *bytes) {
  return ((uint32_t)bytes[0] << 24U) | ((uint32_t)bytes[1] << 16U) |
         ((uint32_t)bytes[2] << 8U) | (uint32_t)bytes[3];
}

static uint64_t fnv1a(const unsigned char *bytes, size_t byte_count) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (size_t i = 0; i < byte_count; ++i) {
    hash ^= bytes[i];
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

static const unsigned char *find_bytes(const unsigned char *haystack,
                                       size_t haystack_size,
                                       const unsigned char *needle,
                                       size_t needle_size) {
  for (size_t i = 0; i + needle_size <= haystack_size; ++i) {
    if (memcmp(haystack + i, needle, needle_size) == 0) {
      return haystack + i;
    }
  }
  return NULL;
}

static void test_model_1_stream_has_exact_record_shape(void) {
  const unsigned char pattern[] = {0xaa, 0xa8, 0x55, 0x50};
  const struct hplj_raster raster = tiny_raster(pattern);
  struct capture capture = {0};
  const struct hplj_encode_result result = hplj_encode_raster(
      hplj_foo2zjs_model_1(), &raster,
      &(struct hplj_encoder_sink){.emit = capture_emit, .context = &capture}, false);

  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(result.bytes_emitted == capture.size);
  static const unsigned char magic[] = {'J', 'Z', 'J', 'Z'};
  const unsigned char *record = find_bytes(capture.bytes, capture.size, magic, sizeof(magic));
  assert(record != NULL);
  record += sizeof(magic);
  const unsigned char *end = capture.bytes + capture.size;
  const uint32_t expected_types[] = {0, 2, 4, 5, 6, 3, 1};
  size_t type_index = 0;
  while (record + 16 <= end && type_index < sizeof(expected_types) / sizeof(expected_types[0])) {
    const uint32_t size = read_be32(record);
    assert(size >= 16);
    assert(record + size <= end);
    assert(read_be32(record + 4) == expected_types[type_index++]);
    assert(record[14] == 'Z' && record[15] == 'Z');
    if (read_be32(record + 4) == 4) {
      assert(size == 36);
      assert(read_be32(record + 16 + 4) == 128);
      assert(read_be32(record + 16 + 8) == 2);
    }
    record += size;
  }
  assert(type_index == sizeof(expected_types) / sizeof(expected_types[0]));
  assert(find_bytes(capture.bytes, capture.size,
                    (const unsigned char *)"@PJL EOJ\n", 9) != NULL);
}

static void test_raster_header_is_fully_validated_before_encoding(void) {
  const unsigned char pattern[] = {0xaa, 0xa8, 0x55, 0x50};
  struct hplj_raster raster = tiny_raster(pattern);
  struct fake_encoder encoder = {0};

#define EXPECT_INVALID(field, value, restore)                             \
  do {                                                                    \
    raster.field = (value);                                               \
    assert(encode_with_fake(&raster, &encoder, false).error.category ==   \
           HPLJ_ERROR_RASTER_INVALID);                                    \
    assert(encoder.calls == 0);                                           \
    raster.field = (restore);                                             \
  } while (0)

  EXPECT_INVALID(width_pixels, 0, 13);
  EXPECT_INVALID(height_rows, 0, 2);
  EXPECT_INVALID(resolution_dpi, 300, 600);
  EXPECT_INVALID(painted_resolution_dpi, 300, 600);
  EXPECT_INVALID(page_width_pixels, 12, 13);
  EXPECT_INVALID(page_height_rows, 1, 2);
  EXPECT_INVALID(printable_width_pixels, 0, 13);
  EXPECT_INVALID(printable_height_rows, 0, 2);
  EXPECT_INVALID(printable_x_pixels, 1, 0);
  EXPECT_INVALID(printable_y_rows, 1, 0);
  EXPECT_INVALID(row_stride_bytes, 1, 2);
  EXPECT_INVALID(bits_size, 3, 4);
  EXPECT_INVALID(bit_order, (enum hplj_bit_order)99,
                 HPLJ_MOST_SIGNIFICANT_BIT_FIRST);
  EXPECT_INVALID(bit_polarity, (enum hplj_bit_polarity)99,
                 HPLJ_BLACK_IS_ONE);
  EXPECT_INVALID(page_count, 0, 1);
  EXPECT_INVALID(media, (enum hplj_media)99, HPLJ_MEDIA_A4);
  EXPECT_INVALID(source, HPLJ_SOURCE_MANUAL, HPLJ_SOURCE_AUTO);
  EXPECT_INVALID(quality, HPLJ_QUALITY_DRAFT, HPLJ_QUALITY_NORMAL);
  EXPECT_INVALID(density, 2, 3);
#undef EXPECT_INVALID

  assert(encode_with_fake(&raster, &encoder, false).error.category ==
         HPLJ_ERROR_NONE);
  assert(encoder.calls == 1);
}

static void test_normalization_ignores_padding_and_canonicalizes_bits(void) {
  const unsigned char canonical[] = {0xaa, 0xaf, 0x55, 0x57};
  const unsigned char alternate[] = {0xaa, 0xa8, 0x55, 0x50};
  struct hplj_raster first = tiny_raster(canonical);
  struct hplj_raster second = tiny_raster(alternate);
  struct capture first_capture = {0};
  struct capture second_capture = {0};
  assert(hplj_encode_raster(
             hplj_foo2zjs_model_1(), &first,
             &(struct hplj_encoder_sink){capture_emit, &first_capture}, false)
             .error.category == HPLJ_ERROR_NONE);
  assert(hplj_encode_raster(
             hplj_foo2zjs_model_1(), &second,
             &(struct hplj_encoder_sink){capture_emit, &second_capture}, false)
             .error.category == HPLJ_ERROR_NONE);
  assert(first_capture.size == second_capture.size);
  assert(memcmp(first_capture.bytes, second_capture.bytes, first_capture.size) == 0);

  const unsigned char lsb_white_is_one[] = {0xaa, 0x0a, 0x55, 0x15};
  second = tiny_raster(lsb_white_is_one);
  second.bit_order = HPLJ_LEAST_SIGNIFICANT_BIT_FIRST;
  second.bit_polarity = HPLJ_BLACK_IS_ZERO;
  second_capture.size = 0;
  assert(hplj_encode_raster(
             hplj_foo2zjs_model_1(), &second,
             &(struct hplj_encoder_sink){capture_emit, &second_capture}, false)
             .error.category == HPLJ_ERROR_NONE);
  assert(first_capture.size == second_capture.size);
  assert(memcmp(first_capture.bytes, second_capture.bytes, first_capture.size) == 0);
}

static uint64_t encode_golden(const unsigned char *bits) {
  const struct hplj_raster raster = tiny_raster(bits);
  struct capture capture = {0};
  const struct hplj_encode_result result = hplj_encode_raster(
      hplj_foo2zjs_model_1(), &raster,
      &(struct hplj_encoder_sink){capture_emit, &capture}, false);
  assert(result.error.category == HPLJ_ERROR_NONE);
  return fnv1a(capture.bytes, capture.size);
}

static uint64_t encode_raster_golden(const struct hplj_raster *raster) {
  struct capture capture = {0};
  const struct hplj_encode_result result = hplj_encode_raster(
      hplj_foo2zjs_model_1(), raster,
      &(struct hplj_encoder_sink){capture_emit, &capture}, false);
  assert(result.error.category == HPLJ_ERROR_NONE);
  return fnv1a(capture.bytes, capture.size);
}

static void test_blank_full_and_patterned_vectors_match_pinned_upstream(void) {
  /*
   * Independent golden values come from pinned foo2zjs with
   * `-z1 -P -L0 -r600x600 -g13x2 -p9`; only JobAttr4 is normalized.
   */
  const unsigned char blank[] = {0x00, 0x00, 0x00, 0x00};
  const unsigned char full[] = {0xff, 0xf8, 0xff, 0xf8};
  const unsigned char pattern[] = {0xaa, 0xa8, 0x55, 0x50};

  assert(encode_golden(blank) == UINT64_C(0xbc5924a1558ec23d));
  assert(encode_golden(full) == UINT64_C(0x29f707faa2f82ea4));
  assert(encode_golden(pattern) == UINT64_C(0xae273fd0dffe5c66));
}

static void test_multi_page_and_clipped_page_are_structurally_complete(void) {
  unsigned char pages[48] = {0};
  memset(pages + 24, 0xff, 24);
  struct hplj_raster raster = tiny_raster(pages);
  raster.page_count = 2;
  raster.width_pixels = 24;
  raster.height_rows = 8;
  raster.bits_size = sizeof(pages);
  raster.page_width_pixels = 24;
  raster.page_height_rows = 8;
  raster.printable_x_pixels = 8;
  raster.printable_y_rows = 4;
  raster.row_stride_bytes = 3;
  struct capture capture = {0};
  const struct hplj_encode_result result = hplj_encode_raster(
      hplj_foo2zjs_model_1(), &raster,
      &(struct hplj_encoder_sink){capture_emit, &capture}, false);
  assert(result.error.category == HPLJ_ERROR_NONE);
  assert(fnv1a(capture.bytes, capture.size) == UINT64_C(0x791e971622b353fa));

  static const unsigned char magic[] = {'J', 'Z', 'J', 'Z'};
  const unsigned char *record = find_bytes(capture.bytes, capture.size, magic, 4) + 4;
  const unsigned char *end = capture.bytes + capture.size;
  unsigned int starts = 0;
  unsigned int ends = 0;
  while (record + 16 <= end) {
    const uint32_t size = read_be32(record);
    assert(size >= 16 && record + size <= end);
    if (read_be32(record + 4) == 2) {
      ++starts;
    }
    ends += read_be32(record + 4) == 3;
    if (read_be32(record + 4) == 1) {
      break;
    }
    record += size;
  }
  assert(starts == 2);
  assert(ends == 2);
}


static void test_clipped_vector_matches_pinned_upstream(void) {
  unsigned char page[24] = {0};
  page[13] = 0xaa;
  page[14] = 0xa8;
  page[16] = 0x55;
  page[17] = 0x50;
  struct hplj_raster raster = tiny_raster(page);
  raster.width_pixels = 24;
  raster.height_rows = 8;
  raster.page_width_pixels = 24;
  raster.page_height_rows = 8;
  raster.printable_x_pixels = 8;
  raster.printable_y_rows = 4;
  raster.row_stride_bytes = 3;
  raster.bits_size = sizeof(page);

  assert(encode_raster_golden(&raster) == UINT64_C(0xae273fd0dffe5c66));
}

static void test_cancellation_allocation_and_io_failures_emit_no_payload(void) {
  const unsigned char pattern[] = {0xaa, 0xa8, 0x55, 0x50};
  struct hplj_raster raster = tiny_raster(pattern);
  struct fake_encoder encoder = {.result = HPLJ_ERROR_ENCODING_FAILED};
  struct hplj_encode_result result = encode_with_fake(&raster, &encoder, true);
  assert(result.error.category == HPLJ_ERROR_CANCELLED);
  assert(encoder.calls == 0);
  result = encode_with_fake(&raster, &encoder, false);
  assert(result.error.category == HPLJ_ERROR_ENCODING_FAILED);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(result.bytes_emitted == 0);

  struct capture failing_sink = {.failure = HPLJ_ERROR_DEVICE_DISCONNECTED};
  result = hplj_encode_raster(
      hplj_foo2zjs_model_1(), &raster,
      &(struct hplj_encoder_sink){capture_emit, &failing_sink}, false);
  assert(result.error.category == HPLJ_ERROR_DEVICE_DISCONNECTED);
  assert(result.error.retry == HPLJ_RETRY_SAFE_AUTOMATIC);
  assert(result.bytes_emitted == 0);
  assert(failing_sink.size == 0);
}

int main(void) {
  test_model_1_stream_has_exact_record_shape();
  test_raster_header_is_fully_validated_before_encoding();
  test_normalization_ignores_padding_and_canonicalizes_bits();
  test_blank_full_and_patterned_vectors_match_pinned_upstream();
  test_multi_page_and_clipped_page_are_structurally_complete();
  test_clipped_vector_matches_pinned_upstream();
  test_cancellation_allocation_and_io_failures_emit_no_payload();
  return 0;
}
