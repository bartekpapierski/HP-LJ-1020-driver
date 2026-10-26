// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef HPLJ_MEDIA_H
#define HPLJ_MEDIA_H

#include <stdbool.h>
#include <stddef.h>

enum hplj_media {
  HPLJ_MEDIA_A4, HPLJ_MEDIA_LETTER, HPLJ_MEDIA_LEGAL, HPLJ_MEDIA_EXECUTIVE,
  HPLJ_MEDIA_A5, HPLJ_MEDIA_A6, HPLJ_MEDIA_JIS_B5, HPLJ_MEDIA_ISO_B5,
  HPLJ_MEDIA_ENV_10, HPLJ_MEDIA_ENV_C5, HPLJ_MEDIA_ENV_DL,
  HPLJ_MEDIA_ENV_MONARCH, HPLJ_MEDIA_POSTCARD,
  HPLJ_MEDIA_DOUBLE_POSTCARD, HPLJ_MEDIA_FANFOLD, HPLJ_MEDIA_16K,
  HPLJ_MEDIA_CUSTOM, HPLJ_MEDIA_INVALID
};
enum hplj_source { HPLJ_SOURCE_AUTO, HPLJ_SOURCE_MANUAL, HPLJ_SOURCE_MAIN,
                   HPLJ_SOURCE_INVALID };

struct hplj_media_size {
  const char *name;
  unsigned int width, length; /* Hundredths of a millimeter, feed axes. */
  unsigned int paper_code;
};

struct hplj_media_geometry {
  size_t width, height, left, top, printable_width, printable_height;
};

#define HPLJ_MEDIA_MARGIN 400U
#define HPLJ_MEDIA_MIN_WIDTH 7600U
#define HPLJ_MEDIA_MIN_LENGTH 12700U
#define HPLJ_MEDIA_MAX_WIDTH 21600U
#define HPLJ_MEDIA_MAX_LENGTH 35600U

const struct hplj_media_size *hplj_media_size(enum hplj_media media);
enum hplj_media hplj_media_from_name(const char *name);
enum hplj_source hplj_source_from_name(const char *name);
unsigned int hplj_source_code(enum hplj_source source);
const char *hplj_source_description(enum hplj_source source);
/* Standard sizes allow 0,0 to request their canonical dimensions. Custom
 * sizes require explicit dimensions. Content orientation is composed by the
 * client: landscape never swaps the physical feed axes or raster dimensions.
 * Match pinned CUPS 2: truncate the sheet and each 4 mm margin. */
bool hplj_media_geometry(enum hplj_media media, unsigned int width,
                         unsigned int length, struct hplj_media_geometry *out);

#endif
