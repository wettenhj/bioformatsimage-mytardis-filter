Bioformats Image MyTardis Filter
===============================

_Only dm3, ims, jp2, lif, nd2, tif and vsi files are supported for now. However, Bioformats supports [many formats](http://loci.wisc.edu/bio-formats/formats) so potentially so will this filter without much effort._

Filter for generating image thumbnails and storing metadata for MyTardis using LOCI Bioformats' command line binaries that interact with their jar file.

![Screenshot](https://dl.dropbox.com/u/172498/screenshots_host/bioformats-dm3.png)

## Todo
 - Support more file types
 - Error handling if the Bioformats tool (bfconvert or showing) fails for whatever reason
 - More detailed metadata parameters than simple text output

## Requirements
 - Java Runtime Environment
 - [MyTardis 3.6 Branch](https://github.com/mytardis/mytardis/branches/3.6)
 - http://cvs.openmicroscopy.org.uk/snapshots/bioformats/4.4.6/bftools.zip
 - http://hudson.openmicroscopy.org.uk/job/BIOFORMATS-trunk/lastSuccessfulBuild/artifact/artifacts/loci_tools.jar

## Installation

 - Unzip bftools.zip into a directory on the MyTardis server
 - Place loci_tools in the same directory as the unzipped bftools
 - Make sure the MyTardis web server user can read the bftools' directory contents

Git clone this repository into `/path/to/mytardis/tardis/tardis_portal/filters`:
    
    git clone git@github.com:wettenhj/bioformatsimage-mytardis-filter.git bioformatsimage

Add the following to your MyTardis settings file eg. `/path/to/mytardis/tardis/settings.py`

```
MIDDLEWARE_CLASSES = MIDDLEWARE_CLASSES + ('tardis.tardis_portal.filters.FilterInitMiddleware',)

FILTER_MIDDLEWARE = (("tardis.tardis_portal.filters", "FilterInitMiddleware"),)
```

The above enables the filter middleware for all actions.

Then add the definition for this filter.

```
POST_SAVE_FILTERS = [
   ("tardis.tardis_portal.filters.bioformatsimage.bioformatsimage.make_filter",
   ["BIOFORMATS", "http://tardis.edu.au/schemas/bioformats/1",
    "/path/to/bftools/bfconvert",
     "/path/to/bftools/showinf"]),
   ]
```

If you want to specify the name of the Celery queue the Bioformats processes
should run in (e.g. "filters"), you can do so as follows:

```
POST_SAVE_FILTERS = [
   ("tardis.tardis_portal.filters.bioformatsimage.bioformatsimage.make_filter",
   ["BIOFORMATS", "http://tardis.edu.au/schemas/bioformats/1",
    "/path/to/bftools/bfconvert",
     "/path/to/bftools/showinf"]),
   {'queue': 'filters'}
   ],
```


Where the bftools directory is correct for your installation.

`cd /path/to/mytardis` and load the parameter schema into the MyTardis database:

```
bin/django loaddata tardis/tardis_portal/filters/bioformatsimage/bioformats.json
```

Restart MyTardis. From now on, all dm3, ims, jp2, lif, nd2, tif and vsi files loaded will have preview images and metadata extracted and stored alongside the file itself.
