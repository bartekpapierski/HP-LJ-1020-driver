// SPDX-License-Identifier: GPL-2.0-or-later
/* Independent pixel oracle for PDF composition, rotation and blank sheets. */
#include <cups/raster.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  int fd = open(argv[1], O_RDONLY);
  if (fd < 0) return 1;
  cups_raster_t *raster = cupsRasterOpen(fd, CUPS_RASTER_READ);
  if (raster == NULL) { close(fd); return 1; }
  cups_page_header2_t header;
  unsigned count = 0;
  while (cupsRasterReadHeader2(raster, &header)) {
    if (header.Duplex || header.Tumble || header.cupsBitsPerPixel != 1 ||
        header.HWResolution[0] != 600 || header.HWResolution[1] != 600 ||
        header.cupsWidth != 4960 || header.cupsHeight != 7015 ||
        header.MediaPosition != 1) return 1;
    unsigned char *line = malloc(header.cupsBytesPerLine);
    if (line == NULL) return 1;
    int left = -1, top = -1, right = -1, bottom = -1;
    for (unsigned y = 0; y < header.cupsHeight; y++) {
      if (cupsRasterReadPixels(raster, line, header.cupsBytesPerLine) !=
          header.cupsBytesPerLine) return 1;
      for (unsigned x = 0; x < header.cupsWidth; x++) {
        if (line[x / 8] & (0x80U >> (x % 8))) {
          if (left < 0 || (int)x < left) left = (int)x;
          if (top < 0) top = (int)y;
          if ((int)x > right) right = (int)x;
          bottom = (int)y;
        }
      }
    }
    free(line);
    printf("%d %d %d %d\n", left, top, right, bottom);
    count++;
  }
  cupsRasterClose(raster);
  close(fd);
  return count == 0;
}
