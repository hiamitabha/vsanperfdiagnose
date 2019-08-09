#!/usr/bin/env python3

# Copyright (c) 2018 Amitabha Banerjee
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License in the file LICENSE.txt or at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ssl
import sys
import logging
import json
import datetime
import time
import vsanmgmtObjects
import optparse
from pyVim import connect
from pyVmomi import vim
from pyVmomi import SoapStubAdapter
from pyVim.task import WaitForTask

def convertVsanTaskToVcTask(vsanTask, vcStub):
   """
      Get a VC task from vSAN task MoId
   """
   vcTask = vim.Task(vsanTask._moId, vcStub)
   return vcTask

def getDiagnosticExceptions(vpm):
   """
      Convert a list of diagnostic exceptions to a dictionary
   """
   exceptionDict = {}
   output = vpm.VsanPerfGetSupportedDiagnosticExceptions()
   # Check message and details
   for diagExceptionType in output:
      exceptionDict[diagExceptionType.exceptionId] =\
      (diagExceptionType.exceptionMessage,
       diagExceptionType.exceptionDetails,
       diagExceptionType.exceptionUrl)
   return exceptionDict

def getClusterInstance(clusterName, serviceInstance):
   """
      Get the cluster MO given the cluster name
   """
   content = serviceInstance.RetrieveContent()
   searchIndex = content.searchIndex
   datacenters = content.rootFolder.childEntity
   for datacenter in datacenters:
      cluster = searchIndex.FindChild(datacenter.hostFolder, clusterName)
      if cluster is not None:
         return cluster
   return None

def connectToVimEndpoint(host, username, password, version='vim.version.version6'):
   """
      Get a service instance
   """
   context = None
   ssl._create_default_https_context = ssl._create_unverified_context
   stub = SoapStubAdapter(host=host, path="/sdk", poolSize=0, version=version)
   si = vim.ServiceInstance('ServiceInstance', stub)
   content = si.content
   logging.info(str([username, password]))
   content.sessionManager.Login(userName=username, password=password)
   return si, content

def processResult(exceptionDict, result):
   """
      Convert the result into a list married with details on each exception

   """
   resultList = []
   for res in result:
      resultList.append((exceptionDict[res.exceptionId], res))
   return resultList

def processRequest(vcIp, vcUser, vcPass, clusterName, goal, startTime,
                   endTime):
   """
      Process the user request with provided credentials
   """
   (si, content) = connectToVimEndpoint(vcIp, vcUser, vcPass)

   cluster = getClusterInstance(clusterName, si)

   vhStub = SoapStubAdapter(host=vcIp,
                            version="vsan.version.version7",
                            path="/vsanHealth",
                            poolSize=0)

   vhStub.cookie = si._stub.cookie

   vpm = vim.cluster.VsanPerformanceManager('vsan-performance-manager',
                                            vhStub)
   #list of possible diagnostic exceptions
   exceptionDict = getDiagnosticExceptions(vpm)

   f = open('result.txt', 'w')
   if startTime is None:
      # In this case query for the last hour
      endTime = datetime.datetime.utcnow()
      startTime = endTime - datetime.timedelta(0, 3600)
   diagQueryType = vim.cluster.VsanPerfDiagnosticQueryType(goal)
   diagQuery = vim.cluster.VsanPerfDiagnoseQuerySpec(
                  startTime = startTime,
                  endTime = endTime,
                  queryType = diagQueryType)
   print ("Starting diagnosis. Will append results in result.txt")
   beginTime = time.time()
   try:
      task = vpm.VsanPerfDiagnoseTask(diagQuery, cluster)
      vcTask = convertVsanTaskToVcTask(task, si._stub)
      WaitForTask(vcTask)
      time.sleep(1)
      transactionId = vcTask.info.result
      result = vpm.GetVsanPerfDiagnosisResult(vcTask, cluster)
      resultList = processResult(exceptionDict, result)
      for item in resultList:
         f.write("Issue: %s\nDetails: %s\nURL: %s\nResult: %s\n"
         %(item[0][0], item[0][1], item[0][2], item[1]))
      duration = time.time() - beginTime
      print ("Time to run performance diagnostics query is %d seconds. Result"
             " in result.txt" % duration)
   except vim.fault.NotFound as ex:
      logging.error(ex)
   f.close()

def main():
   opt = optparse.OptionParser()
   opt.add_option('--username', '-u', type='string', action='store',
                  default='Administrator@vsphere.local',
                  help='vCenter Username with privileges to monitor'
                  'vSphere/vSAN Operations')
   opt.add_option('--password', '-p', type='string', action='store',
                  default='Admin!23',
                  help='password for provided username')
   opt.add_option('--ip', '-i', type='string', action='store',
                  help='vCenter IP Address')
   opt.add_option('--logLevel', '-v', action='store',
                  default='error', help='string log level')
   opt.add_option('--clustername', '-c', action='store', help='Name of cluster'
                  'which we wish to diagnose')
   opt.add_option('--goal', '-g', action='store', default='eval',
                  help='Goal for evaluation of perf diagnostics. See reference'
                  'of vSAN Performance Diagnostics for details')
   opt.add_option('--starttime', '-s', action='store', help='start time for'
                  'evaluation of perf diagnostics', default=None)
   opt.add_option('--endtime', '-e', action='store', help='end time for'
                  'evaluation of perf diagnostics', default=None)

   options, _ = opt.parse_args()
   logLevel = getattr(logging, options.logLevel.upper(), logging.ERROR)
   _logger = logging.getLogger()
   _logger.setLevel(logLevel)
   handler = logging.StreamHandler(sys.stdout) # log to stdout
   handler.setLevel(logLevel)
   logFmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
   handler.setFormatter(logging.Formatter(logFmt))
   _logger.addHandler(handler)

   if not options.clustername:
      raise Exception('Cluster name is mandatory')
   if options.starttime is not None:
      sTime =\
      datetime.datetime.strptime(options.startTime, '%b %d %Y %I:%M%p')
      eTime =\
      datetime.datetime.strptime(options.endTime, '%b %d %Y %I:%M%p')
   else:
      sTime = None
      eTime = None
   processRequest(options.ip, options.username, options.password,
                  options.clustername, options.goal,
                  sTime, eTime)

if __name__ == '__main__':
   main()

