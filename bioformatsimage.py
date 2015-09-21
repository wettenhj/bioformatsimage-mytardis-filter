# -*- coding: utf-8 -*-
#
# Copyright (c) 2010-2011, Monash e-Research Centre
#   (Monash University, Australia)
# Copyright (c) 2010-2011, VeRSI Consortium
#   (Victorian eResearch Strategic Initiative, Australia)
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    *  Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#    *  Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#    *  Neither the name of the VeRSI, the VeRSI Consortium members, nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE REGENTS AND CONTRIBUTORS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"""
bioformatsimage.py

.. moduleauthor:: Steve Androulakis <steve.androulakis@gmail.com>
.. moduleauthor:: James Wettenhall <james.wettenhall@monash.edu>

"""
import logging

from django.conf import settings
from django.core.cache import caches

from tardis.tardis_portal.models import Schema, DatafileParameterSet
from tardis.tardis_portal.models import ParameterName, DatafileParameter
from tardis.tardis_portal.models import DataFile, DataFileObject
import subprocess
import os
import traceback
import urlparse
from celery.task import task

logger = logging.getLogger(__name__)

LOCK_EXPIRE = 60 * 5  # Lock expires in 5 minutes


@task(name="tardis_portal.filters.bioformatsimage.bfconvert",
      ignore_result=True)
def run_bfconvert(bfconvert_path, inputfilename, df_id, schema_id):
    """
    Run Bioformats bfconvert on an image file.
    """
    cache = caches['celery-locks']

    # Locking functions to ensure only one instance of
    # bfconvert operates on each datafile at a time.
    lock_id = 'bioformats-filter-bfconvert-lock-%d' % df_id

    # cache.add fails if if the key already exists
    def acquire_lock(): return cache.add(lock_id, 'true', LOCK_EXPIRE)
    # cache.delete() can be slow, but we have to use it
    # to take advantage of using add() for atomic locking
    def release_lock(): cache.delete(lock_id)

    if acquire_lock():
        try:
            schema = Schema.objects.get(id=schema_id)
            datafile = DataFile.objects.get(id=df_id)
            ps = DatafileParameterSet.objects.filter(schema=schema,
                                                     datafile=datafile).first()
            if ps:
                prev_param = ParameterName.objects.get(schema__id=schema_id,
                                                       name='previewImage')
                if DatafileParameter.objects.filter(parameterset=ps,
                                                    name=prev_param).exists():
                    logger.info("Preview image already exists for df_id %d"
                                % df_id)
                    return

            outputextension = "png"
            dfo = DataFileObject.objects.filter(datafile__id=df_id,
                                                verified=True).first()
            preview_image_rel_file_path = os.path.join(
                os.path.dirname(urlparse.urlparse(dfo.uri).path),
                str(df_id),
                '%s.%s' % (os.path.basename(inputfilename),
                           outputextension))
            preview_image_file_path = os.path.join(
                settings.METADATA_STORE_PATH, preview_image_rel_file_path)

            if not os.path.exists(
                    os.path.dirname(preview_image_file_path)):
                os.makedirs(os.path.dirname(preview_image_file_path))

            # Extract only the first image from the stack:
            cmdline = "'%s' -series 0 -timepoint 0 -channel 0 -z 0 " \
                "'%s' '%s' -overwrite" %\
                (bfconvert_path, inputfilename, preview_image_file_path)
            logger.info(cmdline)
            p = subprocess.Popen(cmdline, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, shell=True)
            stdout, _ = p.communicate()
            if p.returncode != 0:
                logger.error(stdout)
                return
            os.rename(preview_image_file_path,
                      preview_image_file_path + '.bioformats')

            # Run ImageMagick convert with contrast-stretch on an image file.
            # We could probably do this with the Wand Python module instead.
            cmdline = "convert '%s.bioformats' -contrast-stretch 0 '%s'" %\
                (preview_image_file_path, preview_image_file_path)
            logger.info(cmdline)
            p = subprocess.Popen(cmdline, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, shell=True)
            stdout, _ = p.communicate()
            os.unlink(preview_image_file_path + '.bioformats')
            if p.returncode != 0:
                logger.error(stdout)
                return
            try:
                ps = DatafileParameterSet.objects.get(schema__id=schema_id,
                                                      datafile__id=df_id)
            except DatafileParameterSet.DoesNotExist:
                ps = DatafileParameterSet(schema=schema,
                                          datafile=datafile)
                ps.save()
            param_name = ParameterName.objects.get(schema__id=schema_id,
                                                   name='previewImage')
            dfp = DatafileParameter(parameterset=ps, name=param_name)
            dfp.string_value = preview_image_rel_file_path
            dfp.save()
        finally:
            release_lock()


@task(name="tardis_portal.filters.bioformatsimage.showinf", ignore_result=True)
def run_showinf(showinf_path, inputfilename, df_id, schema_id):
    """
    Run Bioformats showinf to extract metadata.
    """
    cache = caches['celery-locks']

    # Locking functions to ensure only one instance of
    # showinf operates on each datafile at a time.
    lock_id = 'bioformats-filter-showinf-lock-%d' % df_id

    # cache.add fails if if the key already exists
    def acquire_lock(): return cache.add(lock_id, 'true', LOCK_EXPIRE)
    # cache.delete() can be slow, but we have to use it
    # to take advantage of using add() for atomic locking
    def release_lock(): cache.delete(lock_id)

    if acquire_lock():
        try:
            schema = Schema.objects.get(id=schema_id)
            datafile = DataFile.objects.get(id=df_id)
            ps = DatafileParameterSet.objects.filter(schema=schema,
                                                     datafile=datafile).first()
            if ps:
                info_param = ParameterName.objects.get(schema__id=schema_id,
                                                       name='image_information')
                if DatafileParameter.objects.filter(parameterset=ps,
                                                    name=info_param).exists():
                    logger.info("Metadata already exists for df_id %d"
                                % df_id)
                    return

            cmdline = "'%s' '%s' -nopix" % (showinf_path, inputfilename)
            logger.info(cmdline)
            p = subprocess.Popen(cmdline, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, shell=True)
            stdout, _ = p.communicate()
            if p.returncode != 0:
                logger.error(stdout)
                return
            image_info_list = stdout.split('\n')[11:]

            # Some/all? of these excludes below are specific to DM3 format:
            exclude_line = dict()
            exclude_line['-----'] = None
            exclude_line['Reading global metadata'] = None
            exclude_line['Reading metadata'] = None
            exclude_line['Reading core metadata'] = None
            exclude_line['Populating metadata'] = None
            exclude_line['Reading tags'] = None
            exclude_line['Verifying Gatan format'] = None
            exclude_line['Initializing reader'] = None
            exclude_line['Checking file format [Gatan Digital Micrograph]'] = \
                None

            try:
                ps = DatafileParameterSet.objects.get(schema__id=schema_id,
                                                      datafile__id=df_id)
            except DatafileParameterSet.DoesNotExist:
                ps = DatafileParameterSet(schema=schema, datafile=datafile)
                ps.save()

            param_name = ParameterName.objects.get(schema__id=schema_id,
                                                   name='image_information')
            for val in reversed(image_info_list):
                strip_val = val.strip()
                if strip_val:
                    if strip_val not in exclude_line:
                        dfp = DatafileParameter(parameterset=ps,
                                                name=param_name)
                        dfp.string_value = strip_val
                        dfp.save()
        finally:
            release_lock()


class BioformatsImageFilter(object):
    """This filter uses the LOCI Bio-formats binaries to get image_information
    about a variety of image formats.

    http://loci.wisc.edu/software/bio-formats

    If a white list is specified then it takes precidence and all
    other tags will be ignored.

    :param name: the short name of the schema.
    :type name: string
    :param schema: the name of the schema to load the EXIF data into.
    :type schema: string
    :param queue: the name of the celery queue to run tasks in.
    :type queue: string
    """
    def __init__(self, name, schema, bfconvert_path, showinf_path,
                 queue=None):
        self.name = name
        self.schema = schema
        self.bfconvert_path = bfconvert_path
        self.showinf_path = showinf_path
        self.queue = queue

    def __call__(self, sender, **kwargs):
        """post save callback entry point.

        :param sender: The model class.
        :param instance: The actual instance being saved.
        :param created: A boolean; True if a new record was created.
        :type created: bool
        """
        instance = kwargs.get('instance')
        schema = Schema.objects.get(namespace__exact=self.schema)

        extension = instance.filename.lower()[-3:]
        if extension not in ('dm3', 'ims', 'jp2', 'lif', 'nd2', 'tif', 'vsi'):
            return None

        # MyTardis's iiif.py can generate a preview image for these file(s):
        generate_preview_image = extension not in ('tif')

        one_gigabyte = 1024 * 1024 * 1024
        if instance.file_object.size > one_gigabyte:
            logger.warning("Refusing to run Bioformats on %s (ID %d), "
                           "because its size (%d) is larger than 1 GB."
                           % (instance.filename, instance.id,
                              instance.file_object.size))
            return None

        if DatafileParameterSet.objects.filter(schema=schema,
                                               datafile=instance).exists():
            ps = DatafileParameterSet.objects.get(schema=schema,
                                                  datafile=instance)
            logger.warning("Parameter set already exists for %s, "
                           "so we'll just return it." % instance.filename)
            return ps

        logger.info("Applying Bioformats filter to '%s'..."
                    % instance.filename)

        # Instead of checking out to a tmpdir, we'll use dfo.get_full_path().
        # This won't work for object storage, but that's OK for now...
        dfo = DataFileObject.objects.filter(datafile=instance,
                                            verified=True).first()
        filepath = dfo.get_full_path()
        logger.info("filepath = '" + filepath + "'")

        try:
            kwargs = {'queue': self.queue} if self.queue else {}
            run_showinf.apply_async(args=[self.showinf_path, filepath,
                                          instance.id, schema.id],
                                    **kwargs)

            if generate_preview_image:
                kwargs = {'queue': self.queue} if self.queue else {}
                run_bfconvert.apply_async(args=[self.bfconvert_path,
                                                filepath,
                                                instance.id,
                                                schema.id],
                                          **kwargs)
        except Exception, e:
            logger.error(traceback.format_exc())
            return None


def make_filter(name='', schema='',
                bfconvert_path=None, showinf_path=None,
                queue=None):
    if not name:
        raise ValueError("BioformatsImageFilter "
                         "requires a name to be specified")
    if not schema:
        raise ValueError("BioformatsImageFilter "
                         "requires a schema to be specified")
    if not bfconvert_path:
        raise ValueError("BioformatsImageFilter "
                         "requires a bfconvert path to be specified")
    if not showinf_path:
        raise ValueError("BioformatsImageFilter "
                         "requires a showinf path to be specified")
    return BioformatsImageFilter(name, schema,
                                 bfconvert_path, showinf_path,
                                 queue)

make_filter.__doc__ = BioformatsImageFilter.__doc__
