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
from fractions import Fraction
import logging

from django.conf import settings

from tardis.tardis_portal.models import Schema, DatafileParameterSet
from tardis.tardis_portal.models import ParameterName, DatafileParameter
from tardis.tardis_portal.models import DataFileObject
import subprocess
import tempfile
import base64
import os
import shutil
import traceback
import urlparse

logger = logging.getLogger(__name__)


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
    :param tagsToFind: a list of the tags to include.
    :type tagsToFind: list of strings
    :param tagsToExclude: a list of the tags to exclude.
    :type tagsToExclude: list of strings
    """
    def __init__(self, name, schema, image_path, metadata_path,
                 tagsToFind=[], tagsToExclude=[]):
        self.name = name
        self.schema = schema
        self.tagsToFind = tagsToFind
        self.tagsToExclude = tagsToExclude
        self.image_path = image_path
        self.metadata_path = metadata_path

    def __call__(self, sender, **kwargs):
        """post save callback entry point.

        :param sender: The model class.
        :param instance: The actual instance being saved.
        :param created: A boolean; True if a new record was created.
        :type created: bool
        """
        instance = kwargs.get('instance')
        schema = self.getSchema()

        extension = instance.filename.lower()[-3:]
        if extension not in ('dm3', 'ims', 'jp2', 'lif', 'nd2', 'tif', 'vsi'):
            return None

        if DatafileParameterSet.objects.filter(schema=schema,
                                               datafile=instance).exists():
            ps = DatafileParameterSet.objects.get(schema=schema,
                                                  datafile=instance)
            print "Parameter set already exists for %s, " \
                "so we'll just return it." % instance.filename
            return ps

        one_gigabyte = 1024 * 1024 * 1024
        if instance.file_object.size > one_gigabyte:
            logger.warning("Refusing to run Bioformats on %s (ID %d), "
                           "because its size (%d) is larger than 1 GB."
                           % (instance.filename, instance.id,
                              instance.file_object.size))
            return None

        print "Applying Bioformats filter to '%s'..." % instance.filename

        tmpdir = tempfile.mkdtemp()

        filepath = os.path.join(tmpdir, instance.filename)
        logger.info("filepath = '" + filepath + "'")

        with instance.file_object as f:
            with open(filepath, 'wb') as g:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    g.write(chunk)

        try:
            outputextension = "png"
            dfos = DataFileObject.objects.filter(datafile=instance)
            preview_image_rel_file_path = os.path.join(
                os.path.dirname(urlparse.urlparse(dfos[0].uri).path),
                str(instance.id),
                '%s.%s' % (os.path.basename(filepath),
                           outputextension))
            logger.info("preview_image_rel_file_path = " +
                        preview_image_rel_file_path)
            preview_image_file_path = os.path.join(
                settings.METADATA_STORE_PATH, preview_image_rel_file_path)
            logger.info("preview_image_file_path = " + preview_image_file_path)

            if not os.path.exists(os.path.dirname(preview_image_file_path)):
                os.makedirs(os.path.dirname(preview_image_file_path))

            bin_imagepath = os.path.basename(self.image_path)
            logger.info("bin_imagepath = " + bin_imagepath)
            cd_imagepath = os.path.dirname(self.image_path)
            logger.info("cd_imagepath = " + cd_imagepath)

            self.fileoutput(cd_imagepath,
                            bin_imagepath,
                            filepath,
                            preview_image_file_path,
                            '-overwrite')

            self.fileoutput('/bin',
                            'mv',
                            preview_image_file_path,
                            preview_image_file_path + '.bioformats')

            self.fileoutput2('/usr/bin',
                             'convert',
                             preview_image_file_path + '.bioformats',
                             '-contrast-stretch 0',
                             preview_image_file_path)

            metadata_dump = dict()
            metadata_dump['previewImage'] = preview_image_rel_file_path

            bin_infopath = os.path.basename(self.metadata_path)
            cd_infopath = os.path.dirname(self.metadata_path)
            image_information = self.textoutput(
                cd_infopath, bin_infopath, filepath, '-nopix').split('\n')[11:]

            if image_information:
                metadata_dump['image_information'] = image_information

            shutil.rmtree(tmpdir)

            self.saveMetadata(instance, schema, metadata_dump)

        except Exception, e:
            print str(e)
            print traceback.format_exc()
            logger.debug(str(e))
            return None

    def saveMetadata(self, instance, schema, metadata):
        """Save all the metadata to a Dataset_Files paramamter set.
        """
        parameters = self.getParameters(schema, metadata)

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
        exclude_line['Checking file format [Gatan Digital Micrograph]'] = None

        if not parameters:
            print "Bailing out of saveMetadata because of 'not parameters'."
            return None

        try:
            ps = DatafileParameterSet.objects.get(schema=schema,
                                                  datafile=instance)
            print "Parameter set already exists for %s, " \
                "so we'll just return it." % instance.filename
            return ps
        except DatafileParameterSet.DoesNotExist:
            ps = DatafileParameterSet(schema=schema,
                                      datafile=instance)
            ps.save()

        for p in parameters:
            print p.name
            if p.name in metadata:
                dfp = DatafileParameter(parameterset=ps,
                                        name=p)
                if p.isNumeric():
                    if metadata[p.name] != '':
                        dfp.numerical_value = metadata[p.name]
                        dfp.save()
                else:
                    print p.name
                    if isinstance(metadata[p.name], list):
                        for val in reversed(metadata[p.name]):
                            strip_val = val.strip()
                            if strip_val:
                                if strip_val not in exclude_line:
                                    dfp = DatafileParameter(parameterset=ps,
                                                            name=p)
                                    dfp.string_value = strip_val
                                    dfp.save()
                    else:
                        dfp.string_value = metadata[p.name]
                        dfp.save()

        return ps

    def getParameters(self, schema, metadata):
        """Return a list of the paramaters that will be saved.
        """
        param_objects = ParameterName.objects.filter(schema=schema)
        parameters = []
        for p in metadata:

            if self.tagsToFind and p not in self.tagsToFind:
                continue

            if p in self.tagsToExclude:
                continue

            parameter = filter(lambda x: x.name == p, param_objects)

            if parameter:
                parameters.append(parameter[0])
                continue

            # detect type of parameter
            datatype = ParameterName.STRING

            # Int test
            try:
                int(metadata[p])
            except ValueError:
                pass
            except TypeError:
                pass
            else:
                datatype = ParameterName.NUMERIC

            # Fraction test
            if isinstance(metadata[p], Fraction):
                datatype = ParameterName.NUMERIC

            # Float test
            try:
                float(metadata[p])
            except ValueError:
                pass
            except TypeError:
                pass
            else:
                datatype = ParameterName.NUMERIC

        return parameters

    def getSchema(self):
        """Return the schema object that the paramaterset will use.
        """
        try:
            return Schema.objects.get(namespace__exact=self.schema)
        except Schema.DoesNotExist:
            schema = Schema(namespace=self.schema, name=self.name,
                            type=Schema.DATAFILE)
            schema.save()
            return schema

    def base64_encode_file(self, filename):
        """encode file from filename in base64
        """
        with open(filename, 'r') as fileobj:
            read = fileobj.read()
            encoded = base64.b64encode(read)
            return encoded

    def exec_command(self, cmd):
        """execute command on shell
        """
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            shell=True)

        p.wait()

        result_str = p.stdout.read()

        return result_str

    def fileoutput(self,
                   cd, execfilename, inputfilename, outputfilename, args=""):
        """execute command on shell with a file output
        """
        cmd = "cd '%s'; ./'%s' '%s' '%s' %s" %\
            (cd, execfilename, inputfilename, outputfilename, args)
        print cmd
        logger.info(cmd)

        return self.exec_command(cmd)

    def fileoutput2(self, cd, execfilename, inputfilename, args1,
                    outputfilename, args2=""):
        """execute command on shell with a file output
        """
        cmd = "cd '%s'; ./'%s' '%s' %s '%s' %s" %\
            (cd, execfilename, inputfilename, args1, outputfilename, args2)
        print cmd
        logger.info(cmd)

        return self.exec_command(cmd)

    def textoutput(self, cd, execfilename, inputfilename, args=""):
        """execute command on shell with a stdout output
        """
        cmd = "cd '%s'; ./'%s' '%s' %s" %\
            (cd, execfilename, inputfilename, args)
        print cmd
        logger.info(cmd)

        return self.exec_command(cmd)


def make_filter(name='', schema='', tagsToFind=[], tagsToExclude=[]):
    if not name:
        raise ValueError("BioformatsImageFilter "
                         "requires a name to be specified")
    if not schema:
        raise ValueError("BioformatsImageFilter "
                         "requires a schema to be specified")
    return BioformatsImageFilter(name, schema, tagsToFind, tagsToExclude)

make_filter.__doc__ = BioformatsImageFilter.__doc__
