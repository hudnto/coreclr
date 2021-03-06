﻿from __future__ import print_function
from genXplatEventing import *
from genXplatLttng import *
import os
import xml.dom.minidom as DOM

stdprolog = """// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

/******************************************************************

DO NOT MODIFY. AUTOGENERATED FILE.
This file is generated using the logic from <root>/src/scripts/genEventPipe.py

******************************************************************/
"""

stdprolog_cmake = """#
#
#******************************************************************

#DO NOT MODIFY. AUTOGENERATED FILE.
#This file is generated using the logic from <root>/src/scripts/genEventPipe.py

#******************************************************************
"""


def generateClrEventPipeWriteEventsImpl(
        providerName, eventNodes, allTemplates, exclusionListFile):
    providerPrettyName = providerName.replace("Windows-", '')
    providerPrettyName = providerPrettyName.replace("Microsoft-", '')
    providerPrettyName = providerPrettyName.replace('-', '_')
    WriteEventImpl = []

    # EventPipeEvent declaration
    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        WriteEventImpl.append(
            "EventPipeEvent *EventPipeEvent" +
            eventName +
            " = nullptr;\n")

    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        templateName = eventNode.getAttribute('template')

        # generate EventPipeEventEnabled function
        eventEnabledImpl = """bool EventPipeEventEnabled%s()
{
    return EventPipeEvent%s->IsEnabled();
}

""" % (eventName, eventName)
        WriteEventImpl.append(eventEnabledImpl)

        # generate EventPipeWriteEvent function
        fnptype = []
        linefnptype = []
        fnptype.append("extern \"C\" ULONG EventPipeWriteEvent")
        fnptype.append(eventName)
        fnptype.append("(\n")

        if templateName:
            template = allTemplates[templateName]
        else:
            template = None

        if template:
            fnSig = template.signature
            for paramName in fnSig.paramlist:
                fnparam = fnSig.getParam(paramName)
                wintypeName = fnparam.winType
                typewName = palDataTypeMapping[wintypeName]
                winCount = fnparam.count
                countw = palDataTypeMapping[winCount]

                if paramName in template.structs:
                    linefnptype.append(
                        "%sint %s_ElementSize,\n" %
                        (lindent, paramName))

                linefnptype.append(lindent)
                linefnptype.append(typewName)
                if countw != " ":
                    linefnptype.append(countw)

                linefnptype.append(" ")
                linefnptype.append(fnparam.name)
                linefnptype.append(",\n")

            if len(linefnptype) > 0:
                del linefnptype[-1]

        fnptype.extend(linefnptype)
        fnptype.append(")\n{\n")
        checking = """    if (!EventPipeEventEnabled%s())
        return ERROR_SUCCESS;
""" % (eventName)

        fnptype.append(checking)

        WriteEventImpl.extend(fnptype)

        if template:
            body = generateWriteEventBody(template, providerName, eventName)
            WriteEventImpl.append(body)
        else:
            WriteEventImpl.append(
                "    EventPipe::WriteEvent(*EventPipeEvent" +
                eventName +
                ", nullptr, 0);\n")

        WriteEventImpl.append("\n    return ERROR_SUCCESS;\n}\n\n")

    # EventPipeProvider and EventPipeEvent initialization
    WriteEventImpl.append(
        "extern \"C\" void Init" +
        providerPrettyName +
        "()\n{\n")
    WriteEventImpl.append(
        "    EventPipeProvider" +
        providerPrettyName +
        " = EventPipe::CreateProvider(" +
        providerPrettyName +
        "GUID);\n")
    for eventNode in eventNodes:
        eventName = eventNode.getAttribute('symbol')
        templateName = eventNode.getAttribute('template')
        eventKeywords = eventNode.getAttribute('keywords')
        eventKeywordsMask = generateEventKeywords(eventKeywords)
        eventValue = eventNode.getAttribute('value')
        eventVersion = eventNode.getAttribute('version')
        eventLevel = eventNode.getAttribute('level')
        eventLevel = eventLevel.replace("win:", "EventPipeEventLevel::")
        exclusionInfo = parseExclusionList(exclusionListFile)
        taskName = eventNode.getAttribute('task')

        initEvent = """    EventPipeEvent%s = EventPipeProvider%s->AddEvent(%s,%s,%s,%s);
""" % (eventName, providerPrettyName, eventValue, eventKeywordsMask, eventVersion, eventLevel)

        WriteEventImpl.append(initEvent)
    WriteEventImpl.append("}")

    return ''.join(WriteEventImpl)


def generateWriteEventBody(template, providerName, eventName):
    header = """
    char stackBuffer[%s];
    char *buffer = stackBuffer;
    unsigned int offset = 0;
    unsigned int size = %s;
    bool fixedBuffer = true;

    bool success = true;
""" % (template.estimated_size, template.estimated_size)

    fnSig = template.signature
    pack_list = []
    for paramName in fnSig.paramlist:
        parameter = fnSig.getParam(paramName)

        if paramName in template.structs:
            size = "(int)%s_ElementSize * (int)%s" % (
                paramName, parameter.prop)
            if template.name in specialCaseSizes and paramName in specialCaseSizes[template.name]:
                size = "(int)(%s)" % specialCaseSizes[template.name][paramName]
            pack_list.append(
                "    success &= WriteToBuffer((const BYTE *)%s, %s, buffer, offset, size, fixedBuffer);" %
                (paramName, size))
        elif paramName in template.arrays:
            size = "sizeof(%s) * (int)%s" % (
                lttngDataTypeMapping[parameter.winType],
                parameter.prop)
            if template.name in specialCaseSizes and paramName in specialCaseSizes[template.name]:
                size = "(int)(%s)" % specialCaseSizes[template.name][paramName]
            pack_list.append(
                "    success &= WriteToBuffer((const BYTE *)%s, %s, buffer, offset, size, fixedBuffer);" %
                (paramName, size))
        elif parameter.winType == "win:GUID":
            pack_list.append(
                "    success &= WriteToBuffer(*%s, buffer, offset, size, fixedBuffer);" %
                (parameter.name,))
        else:
            pack_list.append(
                "    success &= WriteToBuffer(%s, buffer, offset, size, fixedBuffer);" %
                (parameter.name,))

    code = "\n".join(pack_list) + "\n\n"

    checking = """    if (!success)
    {
        if (!fixedBuffer)
            delete[] buffer;
        return ERROR_WRITE_FAULT;
    }\n\n"""

    body = "    EventPipe::WriteEvent(*EventPipeEvent" + \
        eventName + ", (BYTE *)buffer, size);\n"

    footer = """
    if (!fixedBuffer)
        delete[] buffer;
"""

    return header + code + checking + body + footer

providerGUIDMap = {}
providerGUIDMap[
    "{e13c0d23-ccbc-4e12-931b-d9cc2eee27e4}"] = "{0xe13c0d23,0xccbc,0x4e12,{0x93,0x1b,0xd9,0xcc,0x2e,0xee,0x27,0xe4}}"
providerGUIDMap[
    "{A669021C-C450-4609-A035-5AF59AF4DF18}"] = "{0xA669021C,0xC450,0x4609,{0xA0,0x35,0x5A,0xF5,0x9A,0xF4,0xDF,0x18}}"
providerGUIDMap[
    "{CC2BCBBA-16B6-4cf3-8990-D74C2E8AF500}"] = "{0xCC2BCBBA,0x16B6,0x4cf3,{0x89,0x90,0xD7,0x4C,0x2E,0x8A,0xF5,0x00}}"
providerGUIDMap[
    "{763FD754-7086-4dfe-95EB-C01A46FAF4CA}"] = "{0x763FD754,0x7086,0x4dfe,{0x95,0xEB,0xC0,0x1A,0x46,0xFA,0xF4,0xCA}}"


def generateGUID(tmpGUID):
    return providerGUIDMap[tmpGUID]

keywordMap = {}


def generateEventKeywords(eventKeywords):
    mask = 0
    # split keywords if there are multiple
    allKeywords = eventKeywords.split()

    for singleKeyword in allKeywords:
        mask = mask | keywordMap[singleKeyword]

    return mask


def generateEventPipeCmakeFile(etwmanifest, eventpipe_directory):
    tree = DOM.parse(etwmanifest)

    with open(eventpipe_directory + "CMakeLists.txt", 'w') as topCmake:
        topCmake.write(stdprolog_cmake + "\n")
        topCmake.write("""cmake_minimum_required(VERSION 2.8.12.2)

        project(eventpipe)

        set(CMAKE_INCLUDE_CURRENT_DIR ON)
        include_directories(${CLR_DIR}/src/vm)

        add_library(eventpipe
            STATIC\n""")

        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerName = providerName.replace("Windows-", '')
            providerName = providerName.replace("Microsoft-", '')

            providerName_File = providerName.replace('-', '')
            providerName_File = providerName_File.lower()

            topCmake.write('            "%s.cpp"\n' % (providerName_File))
        topCmake.write('            "eventpipehelpers.cpp"\n')
        topCmake.write("""        )

        add_dependencies(eventpipe GeneratedEventingFiles)

        # Install the static eventpipe library
        install(TARGETS eventpipe DESTINATION lib)
        """)

    topCmake.close()


def generateEventPipeHelperFile(etwmanifest, eventpipe_directory):
    with open(eventpipe_directory + "eventpipehelpers.cpp", 'w') as helper:
        helper.write(stdprolog)
        helper.write("""
#include "stdlib.h"

bool ResizeBuffer(char *&buffer, unsigned int& size, unsigned int currLen, unsigned int newSize, bool &fixedBuffer)
{
    newSize *= 1.5;
    _ASSERTE(newSize > size); // check for overflow

    if (newSize < 32)
        newSize = 32;

    char *newBuffer = new char[newSize];

    memcpy(newBuffer, buffer, currLen);

    if (!fixedBuffer)
        delete[] buffer;

    buffer = newBuffer;
    size = newSize;
    fixedBuffer = false;

    return true;
}

bool WriteToBuffer(const BYTE *src, unsigned int len, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer)
{
    if(!src) return true;
    if (offset + len > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + len, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, src, len);
    offset += len;
    return true;
}

bool WriteToBuffer(PCWSTR str, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer)
{
    if(!str) return true;
    unsigned int byteCount = (PAL_wcslen(str) + 1) * sizeof(*str);

    if (offset + byteCount > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + byteCount, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, str, byteCount);
    offset += byteCount;
    return true;
}

bool WriteToBuffer(const char *str, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer)
{
    if(!str) return true;
    unsigned int len = strlen(str) + 1;
    if (offset + len > size)
    {
        if (!ResizeBuffer(buffer, size, offset, size + len, fixedBuffer))
            return false;
    }

    memcpy(buffer + offset, str, len);
    offset += len;
    return true;
}

""")

        tree = DOM.parse(etwmanifest)

        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerPrettyName = providerName.replace("Windows-", '')
            providerPrettyName = providerPrettyName.replace("Microsoft-", '')
            providerPrettyName = providerPrettyName.replace('-', '_')
            helper.write(
                "extern \"C\" void Init" +
                providerPrettyName +
                "();\n\n")

        helper.write("extern \"C\" void InitProvidersAndEvents()\n{\n")
        for providerNode in tree.getElementsByTagName('provider'):
            providerName = providerNode.getAttribute('name')
            providerPrettyName = providerName.replace("Windows-", '')
            providerPrettyName = providerPrettyName.replace("Microsoft-", '')
            providerPrettyName = providerPrettyName.replace('-', '_')
            helper.write("    Init" + providerPrettyName + "();\n")
        helper.write("}")

    helper.close()


def generateEventPipeImplFiles(
        etwmanifest, eventpipe_directory, exclusionListFile):
    tree = DOM.parse(etwmanifest)
    coreclrRoot = os.getcwd()
    for providerNode in tree.getElementsByTagName('provider'):
        providerGUID = providerNode.getAttribute('guid')
        providerGUID = generateGUID(providerGUID)
        providerName = providerNode.getAttribute('name')

        providerPrettyName = providerName.replace("Windows-", '')
        providerPrettyName = providerPrettyName.replace("Microsoft-", '')
        providerName_File = providerPrettyName.replace('-', '')
        providerName_File = providerName_File.lower()
        providerPrettyName = providerPrettyName.replace('-', '_')
        eventpipefile = eventpipe_directory + providerName_File + ".cpp"
        eventpipeImpl = open(eventpipefile, 'w')
        eventpipeImpl.write(stdprolog)

        header = """
#include \"%s/src/vm/common.h\"
#include \"%s/src/vm/eventpipeprovider.h\"
#include \"%s/src/vm/eventpipeevent.h\"
#include \"%s/src/vm/eventpipe.h\"

bool ResizeBuffer(char *&buffer, unsigned int& size, unsigned int currLen, unsigned int newSize, bool &fixedBuffer);
bool WriteToBuffer(PCWSTR str, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer);
bool WriteToBuffer(const char *str, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer);
bool WriteToBuffer(const BYTE *src, unsigned int len, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer);

template <typename T>
bool WriteToBuffer(const T &value, char *&buffer, unsigned int& offset, unsigned int& size, bool &fixedBuffer)
{
    if (sizeof(T) + offset > size)
    {
	    if (!ResizeBuffer(buffer, size, offset, size + sizeof(T), fixedBuffer))
		    return false;
    }

    *(T *)(buffer + offset) = value;
    offset += sizeof(T);
    return true;
}

""" % (coreclrRoot, coreclrRoot, coreclrRoot, coreclrRoot)

        eventpipeImpl.write(header)
        eventpipeImpl.write(
            "GUID const " +
            providerPrettyName +
            "GUID = " +
            providerGUID +
            ";\n")
        eventpipeImpl.write(
            "EventPipeProvider *EventPipeProvider" +
            providerPrettyName +
            " = nullptr;\n")
        templateNodes = providerNode.getElementsByTagName('template')
        allTemplates = parseTemplateNodes(templateNodes)
        eventNodes = providerNode.getElementsByTagName('event')
        eventpipeImpl.write(
            generateClrEventPipeWriteEventsImpl(
                providerName,
                eventNodes,
                allTemplates,
                exclusionListFile) + "\n")
        eventpipeImpl.close()


def generateEventPipeFiles(
        etwmanifest, eventpipe_directory, exclusionListFile):
    eventpipe_directory = eventpipe_directory + "/"
    tree = DOM.parse(etwmanifest)

    if not os.path.exists(eventpipe_directory):
        os.makedirs(eventpipe_directory)

    # generate Cmake file
    generateEventPipeCmakeFile(etwmanifest, eventpipe_directory)

    # generate helper file
    generateEventPipeHelperFile(etwmanifest, eventpipe_directory)

    # generate all keywords
    for keywordNode in tree.getElementsByTagName('keyword'):
        keywordName = keywordNode.getAttribute('name')
        keywordMask = keywordNode.getAttribute('mask')
        keywordMap[keywordName] = int(keywordMask, 0)

    # generate .cpp file for each provider
    generateEventPipeImplFiles(
        etwmanifest,
        eventpipe_directory,
        exclusionListFile)

import argparse
import sys


def main(argv):

    # parse the command line
    parser = argparse.ArgumentParser(
        description="Generates the Code required to instrument eventpipe logging mechanism")

    required = parser.add_argument_group('required arguments')
    required.add_argument('--man', type=str, required=True,
                          help='full path to manifest containig the description of events')
    required.add_argument('--intermediate', type=str, required=True,
                          help='full path to eventprovider  intermediate directory')
    required.add_argument('--exc', type=str, required=True,
                          help='full path to exclusion list')
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print('Unknown argument(s): ', ', '.join(unknown))
        return const.UnknownArguments

    sClrEtwAllMan = args.man
    intermediate = args.intermediate
    exclusionListFile = args.exc

    generateEventPipeFiles(sClrEtwAllMan, intermediate, exclusionListFile)

if __name__ == '__main__':
    return_code = main(sys.argv[1:])
    sys.exit(return_code)
