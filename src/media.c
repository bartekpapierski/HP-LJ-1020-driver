// SPDX-License-Identifier: GPL-2.0-or-later
#include "hplj/media.h"

#include <string.h>

/* Exact-model pinned PPD paper codes; dimensions use PWG feed axes, not
 * the PPD's rounded PostScript points (its ISO B5 dimensions are incorrect). */
static const struct hplj_media_size sizes[] = {
    {"iso_a4_210x297mm", 21000, 29700, 9},
    {"na_letter_8.5x11in", 21590, 27940, 1},
    {"na_legal_8.5x14in", 21590, 35560, 5},
    {"na_executive_7.25x10.5in", 18415, 26670, 7},
    {"iso_a5_148x210mm", 14800, 21000, 11},
    {"iso_a6_105x148mm", 10500, 14800, 262},
    {"jis_b5_182x257mm", 18200, 25700, 13},
    {"iso_b5_176x250mm", 17600, 25000, 259},
    {"na_number-10_4.125x9.5in", 10477, 24130, 20},
    {"iso_c5_162x229mm", 16200, 22900, 28},
    {"iso_dl_110x220mm", 11000, 22000, 27},
    {"na_monarch_3.875x7.5in", 9842, 19050, 37},
    {"jpn_hagaki_100x148mm", 10000, 14800, 260},
    {"jpn_oufuku_148x200mm", 14800, 20000, 261},
    {"na_foolscap_8.5x13in", 21590, 33020, 258},
    {"om_16k_197x273mm", 19700, 27300, 257},
    {NULL, 0, 0, 256},
};

const struct hplj_media_size *hplj_media_size(enum hplj_media media) {
  return (unsigned int)media < sizeof(sizes) / sizeof(sizes[0])
             ? &sizes[media] : NULL;
}

enum hplj_media hplj_media_from_name(const char *name) {
  if (name == NULL) {
    return HPLJ_MEDIA_INVALID;
  }
  for (unsigned int i = 0; i < HPLJ_MEDIA_CUSTOM; i++) {
    if (strcmp(name, sizes[i].name) == 0) {
      return (enum hplj_media)i;
    }
  }
  return strncmp(name, "custom_", 7) == 0 &&
                 strncmp(name, "custom_min_", 11) != 0 &&
                 strncmp(name, "custom_max_", 11) != 0
             ? HPLJ_MEDIA_CUSTOM : HPLJ_MEDIA_INVALID;
}

enum hplj_source hplj_source_from_name(const char *name) {
  if (name == NULL) return HPLJ_SOURCE_INVALID;
  if (strcmp(name, "auto") == 0) return HPLJ_SOURCE_AUTO;
  if (strcmp(name, "main") == 0) return HPLJ_SOURCE_MAIN;
  if (strcmp(name, "manual") == 0) return HPLJ_SOURCE_MANUAL;
  return HPLJ_SOURCE_INVALID;
}

unsigned int hplj_source_code(enum hplj_source source) {
  switch (source) {
    case HPLJ_SOURCE_AUTO: return 7;
    case HPLJ_SOURCE_MAIN: return 1;
    case HPLJ_SOURCE_MANUAL: return 4;
    default: return 0;
  }
}

const char *hplj_source_description(enum hplj_source source) {
  switch (source) {
    case HPLJ_SOURCE_AUTO: return "Automatic feed selected";
    case HPLJ_SOURCE_MAIN: return "Main tray selected; remove sheets from priority feed";
    case HPLJ_SOURCE_MANUAL: return "Priority feed selected; load one sheet";
    default: return "Unsupported media source";
  }
}

bool hplj_media_geometry(enum hplj_media media, unsigned int width,
                         unsigned int length, struct hplj_media_geometry *out) {
  return hplj_media_geometry_for_resolution(media, width, length, 600, out);
}

bool hplj_media_geometry_for_resolution(enum hplj_media media, unsigned int width,
                                        unsigned int length, unsigned int x_dpi,
                                        struct hplj_media_geometry *out) {
  const struct hplj_media_size *size = hplj_media_size(media);
  if (size == NULL || out == NULL || (x_dpi != 600 && x_dpi != 1200)) return false;
  if (media != HPLJ_MEDIA_CUSTOM) {
    if (width == 0 && length == 0) {
      width = size->width;
      length = size->length;
    } else if (width != size->width || length != size->length) {
      return false;
    }
  }
  if (width < HPLJ_MEDIA_MIN_WIDTH || width > HPLJ_MEDIA_MAX_WIDTH ||
      length < HPLJ_MEDIA_MIN_LENGTH || length > HPLJ_MEDIA_MAX_LENGTH) {
    return false;
  }
  *out = (struct hplj_media_geometry){
      .width = width * x_dpi / 2540U,
      .height = length * 600U / 2540U,
      .left = HPLJ_MEDIA_MARGIN * x_dpi / 2540U,
      .top = HPLJ_MEDIA_MARGIN * 600U / 2540U,
  };
  out->printable_width = out->width - 2U * out->left;
  out->printable_height = out->height - 2U * out->top;
  return true;
}
