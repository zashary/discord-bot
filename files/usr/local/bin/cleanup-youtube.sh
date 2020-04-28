#!/bin/bash

# https://stackoverflow.com/questions/32104702/youtube-dl-library-and-error-403-forbidden-when-using-generated-direct-link-by
youtube-dl --rm-cache-dir

# Delete files older than 1 day
find /tmp/ -mtime +1 -delete
