// SPDX-License-Identifier: GPL-2.0-or-later
#include <cups/raster.h>
#include <cups/pwg.h>

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static bool parse_unsigned(const char *text, unsigned int *value) {
  char *end = NULL;
  errno = 0;
  unsigned long parsed = strtoul(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || parsed == 0 ||
      parsed > UINT_MAX) {
    return false;
  }
  *value = (unsigned int)parsed;
  return true;
}

int main(int argc, char *argv[]) {
  if (argc < 3 || argc > 5) {
    return 2;
  }
  unsigned int pages = 1;
  unsigned int pattern = 0x80;
  if (argc >= 4 && !parse_unsigned(argv[3], &pages)) {
    return 2;
  }
  if (argc == 5 && !parse_unsigned(argv[4], &pattern)) {
    return 2;
  }
  cups_mode_t mode;
  if (strcmp(argv[1], "pwg") == 0) {
    mode = CUPS_RASTER_WRITE_PWG;
  } else if (strcmp(argv[1], "apple") == 0) {
    mode = CUPS_RASTER_WRITE_APPLE;
  } else {
    return 2;
  }
  pwg_media_t *media = pwgMediaForPWG("iso_a4_210x297mm");
  cups_page_header2_t header;
  if (media == NULL ||
      !cupsRasterInitPWGHeader(&header, media, "black_1", 600, 600,
                               "one-sided", NULL)) {
    return 1;
  }
  header.cupsInteger[CUPS_RASTER_PWG_TotalPageCount] = pages;
  int fd = open(argv[2], O_CREAT | O_TRUNC | O_WRONLY, 0600);
  if (fd < 0) {
    return 1;
  }
  cups_raster_t *raster = cupsRasterOpen(fd, mode);
  unsigned char *line = calloc(1, header.cupsBytesPerLine);
  if (raster == NULL || line == NULL) {
    free(line);
    if (raster != NULL) {
      cupsRasterClose(raster);
    } else {
      close(fd);
    }
    return 1;
  }
  for (unsigned int page = 0; page < pages; page++) {
    if (!cupsRasterWriteHeader2(raster, &header)) {
      free(line);
      cupsRasterClose(raster);
      return 1;
    }
    line[0] = (unsigned char)((pattern + page) & 0xffU);
    for (unsigned int y = 0; y < header.cupsHeight; y++) {
      if (cupsRasterWritePixels(raster, line, header.cupsBytesPerLine) !=
          header.cupsBytesPerLine) {
        free(line);
        cupsRasterClose(raster);
        return 1;
      }
    }
  }
  free(line);
  cupsRasterClose(raster);
  return 0;
}
