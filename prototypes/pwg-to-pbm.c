// SPDX-License-Identifier: GPL-2.0-or-later
// THROWAWAY PROTOTYPE: extract PAPPL's one-bit PWG raster for foo2zjs.
// This is evidence plumbing, not production conversion code.

#include <cups/raster.h>

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int
main(int argc, char *argv[])
{
  cups_page_header2_t header;
  cups_raster_t *raster;
  unsigned char *line;
  unsigned page = 0;
  int input;

  if (argc != 2)
  {
    fprintf(stderr, "Usage: %s INPUT.pwg > OUTPUT.pbm\n", argv[0]);
    return 2;
  }

  if ((input = open(argv[1], O_RDONLY)) < 0)
  {
    perror(argv[1]);
    return 1;
  }

  if ((raster = cupsRasterOpen(input, CUPS_RASTER_READ)) == NULL)
  {
    fputs("Unable to open PWG raster.\n", stderr);
    close(input);
    return 1;
  }

  while (cupsRasterReadHeader2(raster, &header))
  {
    fprintf(stderr,
            "Page %u: %ux%u pixels, %ux%u dpi, %.2fx%.2f points, "
            "bbox %.2f %.2f %.2f %.2f.\n",
            page + 1, header.cupsWidth, header.cupsHeight,
            header.HWResolution[0], header.HWResolution[1],
            header.cupsPageSize[0], header.cupsPageSize[1],
            header.cupsImagingBBox[0], header.cupsImagingBBox[1],
            header.cupsImagingBBox[2], header.cupsImagingBBox[3]);

    if (header.cupsBitsPerColor != 1 || header.cupsBitsPerPixel != 1 ||
        header.cupsColorOrder != CUPS_ORDER_CHUNKED ||
        header.cupsColorSpace != CUPS_CSPACE_K)
    {
      fprintf(stderr,
              "Page %u is not one-bit chunky black raster (%u/%u/%u/%u).\n",
              page + 1, header.cupsBitsPerColor, header.cupsBitsPerPixel,
              header.cupsColorOrder, header.cupsColorSpace);
      cupsRasterClose(raster);
      return 1;
    }

    if ((line = malloc(header.cupsBytesPerLine)) == NULL)
    {
      fputs("Unable to allocate a raster line.\n", stderr);
      cupsRasterClose(raster);
      return 1;
    }

    fprintf(stdout, "P4\n%u %u\n", header.cupsWidth, header.cupsHeight);
    for (unsigned y = 0; y < header.cupsHeight; y ++)
    {
      if (cupsRasterReadPixels(raster, line, header.cupsBytesPerLine) !=
          header.cupsBytesPerLine ||
          fwrite(line, 1, header.cupsBytesPerLine, stdout) !=
          header.cupsBytesPerLine)
      {
        fprintf(stderr, "Unable to copy raster line %u on page %u.\n", y, page + 1);
        free(line);
        cupsRasterClose(raster);
        return 1;
      }
    }

    free(line);
    page ++;
  }

  cupsRasterClose(raster);
  fprintf(stderr, "Extracted %u page(s).\n", page);
  return page ? 0 : 1;
}
