// SPDX-License-Identifier: GPL-2.0-or-later
#import <AppKit/AppKit.h>

#include <cups/pwg.h>
#include <cups/raster.h>

#include <fcntl.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static bool write_source_page(cups_raster_t *raster,
                              cups_page_header2_t *header,
                              const char *source_path) {
  NSImage *image = [[NSImage alloc]
      initWithContentsOfFile:[NSString stringWithUTF8String:source_path]];
  if (image == nil) {
    return false;
  }
  NSRect proposed = NSMakeRect(0, 0, header->cupsWidth, header->cupsHeight);
  CGImageRef source = [image CGImageForProposedRect:&proposed
                                            context:nil
                                              hints:nil];
  if (source == NULL) {
    return false;
  }
  size_t gray_size = (size_t)header->cupsWidth * header->cupsHeight;
  unsigned char *gray = malloc(gray_size);
  unsigned char *line = calloc(1, header->cupsBytesPerLine);
  CGColorSpaceRef colors = CGColorSpaceCreateDeviceGray();
  CGContextRef context = CGBitmapContextCreate(
      gray, header->cupsWidth, header->cupsHeight, 8, header->cupsWidth,
      colors, (CGBitmapInfo)kCGImageAlphaNone);
  CGColorSpaceRelease(colors);
  if (gray == NULL || line == NULL || context == NULL) {
    free(gray);
    free(line);
    if (context != NULL) {
      CGContextRelease(context);
    }
    return false;
  }
  CGContextSetGrayFillColor(context, 1.0, 1.0);
  CGContextFillRect(context,
                    CGRectMake(0, 0, header->cupsWidth, header->cupsHeight));
  const CGFloat source_width = (CGFloat)CGImageGetWidth(source);
  const CGFloat source_height = (CGFloat)CGImageGetHeight(source);
  const CGFloat scale_x = (CGFloat)header->cupsWidth / source_width;
  const CGFloat scale_y = (CGFloat)header->cupsHeight / source_height;
  const CGFloat scale = scale_x < scale_y ? scale_x : scale_y;
  const CGFloat width = source_width * scale;
  const CGFloat height = source_height * scale;
  CGContextSetInterpolationQuality(context, kCGInterpolationHigh);
  CGContextDrawImage(
      context,
      CGRectMake(((CGFloat)header->cupsWidth - width) / 2.0,
                 ((CGFloat)header->cupsHeight - height) / 2.0, width, height),
      source);

  bool written = cupsRasterWriteHeader2(raster, header);
  for (unsigned int y = 0; written && y < header->cupsHeight; y++) {
    memset(line, 0, header->cupsBytesPerLine);
    for (unsigned int x = 0; x < header->cupsWidth; x++) {
      if (gray[(size_t)y * header->cupsWidth + x] < 128) {
        line[x / 8U] |= (unsigned char)(0x80U >> (x % 8U));
      }
    }
    written = cupsRasterWritePixels(raster, line, header->cupsBytesPerLine) ==
              header->cupsBytesPerLine;
  }
  CGContextRelease(context);
  free(gray);
  free(line);
  return written;
}

static bool write_synthetic_page(cups_raster_t *raster,
                                 cups_page_header2_t *header, bool noise) {
  unsigned char *line = calloc(1, header->cupsBytesPerLine);
  if (line == NULL || !cupsRasterWriteHeader2(raster, header)) {
    free(line);
    return false;
  }
  unsigned int value = 1;
  for (unsigned int y = 0; y < header->cupsHeight; y++) {
    if (noise) {
      for (unsigned int x = 0; x < header->cupsBytesPerLine; x++) {
        value = value * 1664525U + 1013904223U;
        line[x] = (unsigned char)(value >> 24);
      }
    } else {
      line[0] = 0x80;
    }
    if (cupsRasterWritePixels(raster, line, header->cupsBytesPerLine) !=
        header->cupsBytesPerLine) {
      free(line);
      return false;
    }
  }
  free(line);
  return true;
}

int main(int argc, char *argv[]) {
  @autoreleasepool {
    if (argc < 3) {
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
    bool noise = argc == 4 && strcmp(argv[3], "--noise") == 0;
    unsigned int pages = argc > 3 && !noise ? (unsigned int)(argc - 3) : 1U;
    if (media == NULL ||
        !cupsRasterInitPWGHeader(&header, media, "black_1", 600, 600,
                                 "one-sided", NULL)) {
      return 1;
    }
    header.cupsInteger[CUPS_RASTER_PWG_TotalPageCount] = pages;
    int descriptor = open(argv[2], O_CREAT | O_TRUNC | O_WRONLY, 0600);
    if (descriptor < 0) {
      return 1;
    }
    cups_raster_t *raster = cupsRasterOpen(descriptor, mode);
    if (raster == NULL) {
      close(descriptor);
      return 1;
    }
    bool written = true;
    if (argc == 3 || noise) {
      written = write_synthetic_page(raster, &header, noise);
    } else {
      for (int index = 3; written && index < argc; index++) {
        written = write_source_page(raster, &header, argv[index]);
      }
    }
    cupsRasterClose(raster);
    return written ? 0 : 1;
  }
}
