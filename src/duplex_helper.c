// SPDX-License-Identifier: GPL-2.0-or-later
/* Private CLI boundary for scripts/manual_duplex.py: PDF rendering and IPP.
 * Raster pages always carry simplex headers; no duplex opcode reaches USB. */
#include <CoreGraphics/CoreGraphics.h>
#include <cups/cups.h>
#include <cups/pwg.h>
#include <cups/raster.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static CGPDFDocumentRef open_pdf(const char *path) {
  CFURLRef url = CFURLCreateFromFileSystemRepresentation(
      NULL, (const UInt8 *)path, (CFIndex)strlen(path), false);
  CGPDFDocumentRef pdf = url == NULL ? NULL : CGPDFDocumentCreateWithURL(url);
  if (url != NULL) CFRelease(url);
  if (pdf != NULL && (CGPDFDocumentIsEncrypted(pdf) ||
                     CGPDFDocumentGetNumberOfPages(pdf) == 0)) {
    CGPDFDocumentRelease(pdf);
    return NULL;
  }
  return pdf;
}

static bool render_page(cups_raster_t *raster, cups_page_header2_t *header,
                        CGPDFDocumentRef pdf, unsigned page_number,
                        bool landscape, bool rotate) {
  size_t size = (size_t)header->cupsWidth * header->cupsHeight;
  unsigned char *gray = malloc(size);
  unsigned char *line = calloc(1, header->cupsBytesPerLine);
  CGColorSpaceRef colors = CGColorSpaceCreateDeviceGray();
  CGContextRef context = gray == NULL ? NULL : CGBitmapContextCreate(
      gray, header->cupsWidth, header->cupsHeight, 8, header->cupsWidth,
      colors, (CGBitmapInfo)kCGImageAlphaNone);
  CGColorSpaceRelease(colors);
  if (context == NULL || line == NULL) {
    if (context != NULL) CGContextRelease(context);
    free(gray);
    free(line);
    return false;
  }
  CGContextSetGrayFillColor(context, 1, 1);
  CGContextFillRect(context, CGRectMake(0, 0, header->cupsWidth, header->cupsHeight));
  if (page_number != 0) {
    CGPDFPageRef page = CGPDFDocumentGetPage(pdf, page_number);
    if (page == NULL) {
      CGContextRelease(context);
      free(gray);
      free(line);
      return false;
    }
    // Fit content inside the runtime's 4 mm imageable margins. Landscape is
    // host composition; physical A4 feed axes and raster dimensions stay fixed.
    double margin = floor(400.0 * 600.0 / 2540.0);
    CGRect target = CGRectMake(margin, margin, header->cupsWidth - 2 * margin,
                               header->cupsHeight - 2 * margin);
    if (rotate) {
      CGContextTranslateCTM(context, header->cupsWidth, header->cupsHeight);
      CGContextRotateCTM(context, 3.14159265358979323846);
    }
    CGAffineTransform transform = CGPDFPageGetDrawingTransform(
        page, kCGPDFMediaBox, target, landscape ? 90 : 0, true);
    CGContextConcatCTM(context, transform);
    CGContextDrawPDFPage(context, page);
  }
  bool ok = cupsRasterWriteHeader2(raster, header);
  for (unsigned y = 0; ok && y < header->cupsHeight; y++) {
    memset(line, 0, header->cupsBytesPerLine);
    for (unsigned x = 0; x < header->cupsWidth; x++) {
      if (gray[(size_t)y * header->cupsWidth + x] < 128)
        line[x / 8] |= (unsigned char)(0x80U >> (x % 8));
    }
    ok = cupsRasterWritePixels(raster, line, header->cupsBytesPerLine) ==
         header->cupsBytesPerLine;
  }
  CGContextRelease(context);
  free(gray);
  free(line);
  return ok;
}

static int render(int argc, char **argv) {
  CGPDFDocumentRef pdf = open_pdf(argv[2]);
  if (pdf == NULL) return 1;
  cups_page_header2_t header;
  bool ok = cupsRasterInitPWGHeader(&header, pwgMediaForPWG("iso_a4_210x297mm"),
                                    "black_1", 600, 600, "one-sided", NULL);
  header.MediaPosition = 1; // Main tray, never priority feed.
  header.cupsInteger[CUPS_RASTER_PWG_TotalPageCount] = (unsigned)(argc - 6);
  int fd = open(argv[3], O_CREAT | O_EXCL | O_WRONLY, 0600);
  cups_raster_t *raster = fd < 0 ? NULL : cupsRasterOpen(fd, CUPS_RASTER_WRITE_PWG);
  if (raster == NULL) ok = false;
  for (int index = 6; ok && index < argc; index++) {
    char *end;
    unsigned long number = strtoul(argv[index], &end, 10);
    ok = *end == '\0' && number <= CGPDFDocumentGetNumberOfPages(pdf) &&
         render_page(raster, &header, pdf, (unsigned)number,
                     strcmp(argv[4], "landscape") == 0, strcmp(argv[5], "180") == 0);
  }
  if (raster != NULL) cupsRasterClose(raster);
  if (fd >= 0) close(fd);
  CGPDFDocumentRelease(pdf);
  return ok ? 0 : 1;
}

static int ipp_command(int argc, char **argv) {
  int port = atoi(argv[2]);
  if (port <= 0 || port > 65535) return 2;
  http_t *http = httpConnect2("127.0.0.1", port, NULL, AF_INET,
                              HTTP_ENCRYPTION_IF_REQUESTED, 1, 10000, NULL);
  if (http == NULL) {
    fprintf(stderr, "cannot connect to local provider on port %d: %s; "
                    "check that the personal-use service is enabled\n", port, strerror(errno));
    return 1;
  }
  httpSetTimeout(http, 15, NULL, NULL);
  ipp_op_t op;
  if (!strcmp(argv[1], "instance") && argc == 3) op = IPP_OP_GET_PRINTER_ATTRIBUTES;
  else if (!strcmp(argv[1], "create") && argc == 3) op = IPP_OP_CREATE_JOB;
  else if (!strcmp(argv[1], "send") && argc == 5) op = IPP_OP_SEND_DOCUMENT;
  else if (!strcmp(argv[1], "state") && argc == 4) op = IPP_OP_GET_JOB_ATTRIBUTES;
  else if (!strcmp(argv[1], "cancel") && argc == 4) op = IPP_OP_CANCEL_JOB;
  else { httpClose(http); return 2; }
  char uri[128];
  snprintf(uri, sizeof(uri), "ipp://127.0.0.1:%d/ipp/print", port);
  ipp_t *request = ippNewRequest(op);
  ippAddString(request, IPP_TAG_OPERATION, IPP_TAG_URI, "printer-uri", NULL, uri);
  ippAddString(request, IPP_TAG_OPERATION, IPP_TAG_NAME, "requesting-user-name", NULL, cupsUser());
  if (op == IPP_OP_GET_PRINTER_ATTRIBUTES) {
    ippAddString(request, IPP_TAG_OPERATION, IPP_TAG_KEYWORD,
                 "requested-attributes", NULL, "hplj-service-instance");
  } else if (op == IPP_OP_CREATE_JOB) {
    ippAddString(request, IPP_TAG_OPERATION, IPP_TAG_NAME, "job-name", NULL, "Manual duplex pass");
    ippAddString(request, IPP_TAG_JOB, IPP_TAG_KEYWORD, "sides", NULL, "one-sided");
    ippAddString(request, IPP_TAG_JOB, IPP_TAG_KEYWORD, "media", NULL, "iso_a4_210x297mm");
    ippAddString(request, IPP_TAG_JOB, IPP_TAG_KEYWORD, "media-source", NULL, "main");
    ippAddInteger(request, IPP_TAG_JOB, IPP_TAG_INTEGER, "copies", 1);
  } else {
    ippAddInteger(request, IPP_TAG_OPERATION, IPP_TAG_INTEGER, "job-id", atoi(argv[3]));
  }
  if (op == IPP_OP_SEND_DOCUMENT) {
    ippAddString(request, IPP_TAG_OPERATION, IPP_TAG_MIMETYPE, "document-format", NULL, "image/pwg-raster");
    ippAddBoolean(request, IPP_TAG_OPERATION, "last-document", 1);
  }
  ipp_t *response = op == IPP_OP_SEND_DOCUMENT
      ? cupsDoFileRequest(http, request, "/ipp/print", argv[4])
      : cupsDoRequest(http, request, "/ipp/print");
  bool ok = response != NULL && ippGetStatusCode(response) == IPP_STATUS_OK;
  if (ok && op == IPP_OP_GET_PRINTER_ATTRIBUTES) {
    ipp_attribute_t *attr = ippFindAttribute(response, "hplj-service-instance", IPP_TAG_TEXT);
    const char *value = attr == NULL ? NULL : ippGetString(attr, 0, NULL);
    ok = value != NULL && strlen(value) == 32;
    if (ok) {
      puts(value);
    } else {
      fprintf(stderr, "local provider lacks a valid hplj-service-instance attribute; "
                      "refresh the installed provider using the tagged-source update workflow "
                      "(scripts/personal_install.py update --tag TAG --apply --yes); "
                      "building alone does not update the running service\n");
      ippDelete(response);
      httpClose(http);
      return 1;
    }
  }
  if (ok && (op == IPP_OP_CREATE_JOB || op == IPP_OP_GET_JOB_ATTRIBUTES)) {
    ipp_attribute_t *attr = ippFindAttribute(response,
        op == IPP_OP_CREATE_JOB ? "job-id" : "job-state",
        op == IPP_OP_CREATE_JOB ? IPP_TAG_INTEGER : IPP_TAG_ENUM);
    ok = attr != NULL;
    if (ok) printf("%d\n", ippGetInteger(attr, 0));
  }
  if (!ok) fprintf(stderr, "IPP operation unsuccessful: %s\n",
                    response == NULL ? cupsLastErrorString() : ippErrorString(ippGetStatusCode(response)));
  ippDelete(response);
  httpClose(http);
  return ok ? 0 : 1;
}

int main(int argc, char **argv) {
  if (argc == 3 && !strcmp(argv[1], "count")) {
    CGPDFDocumentRef pdf = open_pdf(argv[2]);
    if (pdf == NULL) return 1;
    printf("%zu\n", CGPDFDocumentGetNumberOfPages(pdf));
    CGPDFDocumentRelease(pdf);
    return 0;
  }
  if (argc >= 7 && !strcmp(argv[1], "render")) return render(argc, argv);
  if (argc >= 3) return ipp_command(argc, argv);
  return 2;
}
