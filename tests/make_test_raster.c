// SPDX-License-Identifier: GPL-2.0-or-later
#include <cups/raster.h>
#include <cups/pwg.h>

#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
  if (argc != 3) {
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
  header.cupsInteger[CUPS_RASTER_PWG_TotalPageCount] = 1;
  int fd = open(argv[2], O_CREAT | O_TRUNC | O_WRONLY, 0600);
  if (fd < 0) {
    return 1;
  }
  cups_raster_t *raster = cupsRasterOpen(fd, mode);
  unsigned char *line = calloc(1, header.cupsBytesPerLine);
  if (raster == NULL || line == NULL || !cupsRasterWriteHeader2(raster, &header)) {
    free(line);
    if (raster != NULL) {
      cupsRasterClose(raster);
    } else {
      close(fd);
    }
    return 1;
  }
  line[0] = 0x80;
  for (unsigned int y = 0; y < header.cupsHeight; y++) {
    if (cupsRasterWritePixels(raster, line, header.cupsBytesPerLine) !=
        header.cupsBytesPerLine) {
      free(line);
      cupsRasterClose(raster);
      return 1;
    }
  }
  free(line);
  cupsRasterClose(raster);
  return 0;
}
