// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/encoder.h"
#include "hplj/pappl.h"

#include <cups/pwg.h>
#include <cups/raster.h>
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct capture { unsigned char *bytes; size_t size; };

static enum hplj_error_category emit(void *context, const unsigned char *bytes,
                                      size_t size) {
  struct capture *capture = context;
  capture->bytes = realloc(capture->bytes, capture->size + size);
  assert(capture->bytes != NULL);
  memcpy(capture->bytes + capture->size, bytes, size);
  capture->size += size;
  return HPLJ_ERROR_NONE;
}

static uint32_t be32(const unsigned char *p) {
  return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
         (uint32_t)p[2] << 8 | p[3];
}

static struct hplj_raster raster_for_resolution(enum hplj_media media, unsigned width,
                                                 unsigned length, unsigned dpi) {
  static unsigned char bits[1276U * 8410U];
  struct hplj_media_geometry g;
  assert(hplj_media_geometry_for_resolution(media, width, length, dpi, &g));
  return (struct hplj_raster){
      .width_pixels = g.width, .height_rows = g.height,
      .page_width_pixels = g.width, .page_height_rows = g.height,
      .printable_x_pixels = g.left, .printable_y_rows = g.top,
      .printable_width_pixels = g.printable_width,
      .printable_height_rows = g.printable_height,
      .row_stride_bytes = (g.width + 7) / 8,
      .bits = bits, .bits_size = sizeof(bits),
      .resolution_dpi = dpi, .painted_resolution_dpi = 600,
      .page_count = 1, .media = media, .media_width = width, .media_length = length,
      .source = HPLJ_SOURCE_AUTO,
      .quality = dpi == 600 ? HPLJ_QUALITY_NORMAL : HPLJ_QUALITY_HIGH, .density = 3,
  };
}

static struct hplj_raster raster_for(enum hplj_media media, unsigned width,
                                      unsigned length) {
  return raster_for_resolution(media, width, length, 600);
}

static struct hplj_encode_result encode(struct hplj_raster *r,
                                         struct capture *capture) {
  return hplj_encode_raster(hplj_foo2zjs_model_1(), r,
      &(struct hplj_encoder_sink){emit, capture}, false);
}

static void assert_page_metadata(struct hplj_raster *r) {
  struct capture capture = {0};
  assert(encode(r, &capture).error.category == HPLJ_ERROR_NONE);
  size_t offset = 0;
  while (offset + 4 < capture.size && memcmp(capture.bytes + offset, "JZJZ", 4)) offset++;
  assert(offset + 4 < capture.size);
  offset += 4;
  bool page = false, bih = false;
  while (offset + 16 <= capture.size) {
    const unsigned char *p = capture.bytes + offset;
    uint32_t size = be32(p), type = be32(p + 4);
    assert(size >= 16 && size <= capture.size - offset);
    if (type == 2) {
      page = true;
      unsigned checked = 0;
      for (size_t i = 16; i + 12 <= size; i += 12) {
        unsigned item = (unsigned)p[i + 4] << 8 | p[i + 5];
        uint32_t value = be32(p + i + 8);
        switch (item) {
          case 3: assert(value == hplj_media_size(r->media)->paper_code); checked++; break;
          case 5: assert(value == hplj_source_code(r->source)); checked++; break;
          case 8: case 9: assert(value == 600); checked++; break;
          case 12: assert(value == r->printable_width_pixels); checked++; break;
          case 17: assert(value == r->printable_width_pixels / (r->resolution_dpi / 600)); checked++; break;
          case 16: assert(value == r->resolution_dpi / 600); checked++; break;
          case 13: case 18: assert(value == r->printable_height_rows); checked++; break;
        }
      }
      assert(checked == 9);
    } else if (type == 4) {
      bih = true;
      assert(be32(p + 20) == ((r->printable_width_pixels + 127U) & ~127U));
      assert(be32(p + 24) == r->printable_height_rows);
    } else if (type == 1) break;
    offset += size;
  }
  assert(page && bih);
  free(capture.bytes);
}

static void test_standard_sizes_match_cups_and_zjstream(void) {
  for (int i = 0; i < HPLJ_MEDIA_CUSTOM; i++) {
    enum hplj_media media = (enum hplj_media)i;
    const struct hplj_media_size *size = hplj_media_size(media);
    assert(hplj_media_from_name(size->name) == media);
    pwg_media_t *pwg = pwgMediaForPWG(size->name);
    assert(pwg && pwg->width == (int)size->width && pwg->length == (int)size->length);
    for (unsigned dpi = 600; dpi <= 1200; dpi += 600) {
      cups_page_header2_t header;
      assert(cupsRasterInitPWGHeader(&header, pwg, "black_1", dpi, 600, "one-sided", NULL));
      struct hplj_raster r = raster_for_resolution(media, size->width, size->length, dpi);
      assert(header.cupsWidth == r.width_pixels && header.cupsHeight == r.height_rows);
      assert_page_metadata(&r);
    }
  }
}

static void test_custom_boundaries_rounding_and_orientation(void) {
  struct hplj_media_geometry g;
  assert(hplj_media_geometry(HPLJ_MEDIA_CUSTOM, 7600, 12700, &g));
  assert(g.width == 1795 && g.height == 3000 && g.left == 94 && g.top == 94);
  assert(hplj_media_geometry(HPLJ_MEDIA_CUSTOM, 21600, 35600, &g));
  assert(g.width == 5102 && g.height == 8409);
  const unsigned invalid[][2] = {{7599,12700},{7600,12699},{21601,35600},
                               {21600,35601},{0,0},{29700,21000},{UINT32_MAX,UINT32_MAX}};
  for (size_t i = 0; i < sizeof(invalid)/sizeof(invalid[0]); i++) {
    assert(!hplj_media_geometry(HPLJ_MEDIA_CUSTOM, invalid[i][0], invalid[i][1], &g));
  }
  assert(!hplj_media_geometry(HPLJ_MEDIA_A4, 21590, 27940, &g));
  assert(!hplj_media_geometry(HPLJ_MEDIA_A4, 0, 29700, &g));
  assert(hplj_media_geometry(HPLJ_MEDIA_CUSTOM, 7603, 12703, &g));
  assert(g.width == 1795 && g.height == 3000);
  assert(hplj_media_geometry(HPLJ_MEDIA_CUSTOM, 7604, 12704, &g));
  assert(g.width == 1796 && g.height == 3000);
  for (unsigned i = 0; i < 2; i++) {
    struct hplj_raster r = raster_for(HPLJ_MEDIA_CUSTOM, i ? 21600 : 7600, i ? 35600 : 12700);
    assert_page_metadata(&r);
    r = raster_for_resolution(HPLJ_MEDIA_CUSTOM, i ? 21600 : 7600, i ? 35600 : 12700, 1200);
    assert_page_metadata(&r);
  }
  struct hplj_raster r = raster_for(HPLJ_MEDIA_A4, 0, 0);
  size_t temp = r.width_pixels;
  r.width_pixels = r.page_width_pixels = r.height_rows;
  r.height_rows = r.page_height_rows = temp;
  struct capture capture = {0};
  assert(encode(&r, &capture).error.category == HPLJ_ERROR_RASTER_INVALID);
  assert(capture.size == 0);
}

static void test_sources_and_conflicts(void) {
  const char *names[] = {"auto", "manual", "main"};
  const unsigned codes[] = {7, 4, 1};
  for (unsigned i = 0; i < 3; i++) {
    assert(hplj_source_from_name(names[i]) == (enum hplj_source)i);
    assert(hplj_source_code((enum hplj_source)i) == codes[i]);
    assert(strlen(hplj_source_description((enum hplj_source)i)) > 10);
    struct hplj_raster r = raster_for(HPLJ_MEDIA_A4, 0, 0);
    r.source = (enum hplj_source)i;
    assert_page_metadata(&r);
  }
  assert(hplj_media_from_name("iso_a3_297x420mm") == HPLJ_MEDIA_INVALID);
  assert(hplj_media_from_name(NULL) == HPLJ_MEDIA_INVALID);
  assert(hplj_source_from_name("tray-2") == HPLJ_SOURCE_INVALID);
  assert(hplj_source_from_name(NULL) == HPLJ_SOURCE_INVALID);
  struct hplj_raster r = raster_for(HPLJ_MEDIA_A4, 0, 0);
  r.source = HPLJ_SOURCE_INVALID;
  struct capture capture = {0};
  assert(encode(&r, &capture).error.category == HPLJ_ERROR_RASTER_INVALID);
  assert(capture.size == 0);
}

static void paint(struct hplj_raster *r, size_t x, size_t y) {
  unsigned char *bits = (unsigned char *)r->bits;
  bits[y * r->row_stride_bytes + x / 8] |= (unsigned char)(0x80U >> (x % 8));
}

static void test_physical_margins_clip_only_outside_marks(void) {
  struct hplj_raster r = raster_for(HPLJ_MEDIA_A4, 0, 0);
  struct capture blank = {0}, outside = {0}, inside = {0};
  assert(encode(&r, &blank).error.category == HPLJ_ERROR_NONE);
  const size_t left = r.printable_x_pixels, top = r.printable_y_rows;
  const size_t right = left + r.printable_width_pixels - 1;
  const size_t bottom = top + r.printable_height_rows - 1;
  paint(&r, left - 1, top);
  paint(&r, right + 1, top);
  paint(&r, left, top - 1);
  paint(&r, left, bottom + 1);
  assert(encode(&r, &outside).error.category == HPLJ_ERROR_NONE);
  assert(blank.size == outside.size && !memcmp(blank.bytes, outside.bytes, blank.size));
  paint(&r, left, top);
  paint(&r, right, bottom);
  assert(encode(&r, &inside).error.category == HPLJ_ERROR_NONE);
  assert(blank.size != inside.size || memcmp(blank.bytes, inside.bytes, blank.size));
  memset((unsigned char *)r.bits, 0, r.bits_size);
  free(blank.bytes);
  free(outside.bytes);
  free(inside.bytes);
}

int main(void) {
  test_standard_sizes_match_cups_and_zjstream();
  test_custom_boundaries_rounding_and_orientation();
  test_sources_and_conflicts();
  test_physical_margins_clip_only_outside_marks();
  return 0;
}
