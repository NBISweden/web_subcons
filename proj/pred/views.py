import os
import sys
import tempfile
import re
import subprocess
from datetime import datetime
from pytz import timezone
import time
import math
import shutil
import json
TZ = 'Europe/Stockholm'
os.environ['TZ'] = TZ
time.tzset()

# for dealing with IP address and country names
from geoip import geolite2
import pycountry

#import models for spyne
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.views.decorators.csrf import csrf_exempt  
from spyne.error import ResourceNotFoundError, ResourceAlreadyExistsError
from spyne.server.django import DjangoApplication
from spyne.model.primitive import Unicode, Integer
from spyne.model.complex import Iterable
from spyne.service import ServiceBase
from spyne.protocol.soap import Soap11
from spyne.application import Application
from spyne.decorator import rpc
from spyne.util.django import DjangoComplexModel, DjangoServiceBase
from spyne.server.wsgi import WsgiApplication

# for user authentication
from django.contrib.auth import authenticate, login, logout

# import variables from settings
from django.conf import settings

# add eztables
from django.template import add_to_builtins
add_to_builtins('eztables.templatetags.eztables')

# global parameters
g_params = {}
g_params['BASEURL'] = "/pred/";
g_params['MAXSIZE_UPLOAD_FILE_IN_MB']  = 100
g_params['MAX_DAYS_TO_SHOW']  = 100000
g_params['BIG_NUMBER']  = 100000
g_params['MAX_NUMSEQ_FOR_FORCE_RUN']  = 100
g_params['AVERAGE_RUNTIME_PER_SEQ_IN_SEC']  = 120
g_params['MAX_ROWS_TO_SHOW_IN_TABLE']  = 2000
g_params['MIN_LEN_SEQ']  = 30      # minimum length of the query sequence
g_params['MAX_LEN_SEQ']  = 10000   # maximum length of the query sequence
g_params['MAX_NUMSEQ_PER_JOB'] = 50000
g_params['MAXSIZE_UPLOAD_FILE_IN_BYTE']  = g_params['MAXSIZE_UPLOAD_FILE_IN_MB'] * 1024*1024
g_params['FORMAT_DATETIME'] = "%Y-%m-%d %H:%M:%S %Z"
g_params['DEBUG'] = False

SITE_ROOT = os.path.dirname(os.path.realpath(__file__))
progname =  os.path.basename(__file__)
rootname_progname = os.path.splitext(progname)[0]
path_app = "%s/app"%(SITE_ROOT)
sys.path.append(path_app)
path_log = "%s/static/log"%(SITE_ROOT)
path_stat = "%s/stat"%(path_log)
path_result = "%s/static/result"%(SITE_ROOT)
path_tmp = "%s/static/tmp"%(SITE_ROOT)
path_md5 = "%s/static/md5"%(SITE_ROOT)

python_exec = os.path.realpath("%s/../../env/bin/python"%(SITE_ROOT))


import myfunc
import webserver_common

suq_basedir = "/tmp"
if os.path.exists("/scratch"):
    suq_basedir = "/scratch"
elif os.path.exists("/tmp"):
    suq_basedir = "/tmp"
rundir = SITE_ROOT
suq_exec = "/usr/bin/suq";

qd_fe_scriptfile = "%s/qd_fe.py"%(path_app)
gen_errfile = "%s/static/log/%s_err"%(SITE_ROOT, progname)
gen_logfile = "%s/static/log/%s_log"%(SITE_ROOT, progname)

# Create your views here.
from django.shortcuts import render
from django.http import HttpResponse
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.views.static import serve


#from pred.models import Query
from pred.models import SubmissionForm
from pred.models import SubmissionForm_findjob
from pred.models import FieldContainer
from django.template import Context, loader

def index(request):#{{{
    if not os.path.exists(path_result):
        os.mkdir(path_result, 0755)
    if not os.path.exists(path_result):
        os.mkdir(path_tmp, 0755)
    if not os.path.exists(path_md5):
        os.mkdir(path_md5, 0755)
    base_www_url_file = "%s/static/log/base_www_url.txt"%(SITE_ROOT)
    if not os.path.exists(base_www_url_file):
        base_www_url = "http://" + request.META['HTTP_HOST']
        myfunc.WriteFile(base_www_url, base_www_url_file, "w", True)

    # read the local config file if exists
    configfile = "%s/config/config.json"%(SITE_ROOT)
    config = {}
    if os.path.exists(configfile):
        text = myfunc.ReadFile(configfile)
        config = json.loads(text)

    if rootname_progname in config:
        g_params.update(config[rootname_progname])
        g_params['MAXSIZE_UPLOAD_FILE_IN_BYTE'] = g_params['MAXSIZE_UPLOAD_FILE_IN_MB'] * 1024*1024

    return submit_seq(request)
#}}}
def SetColorStatus(status):#{{{
    if status == "Finished":
        return "green"
    elif status == "Failed":
        return "red"
    elif status == "Running":
        return "blue"
    else:
        return "black"
#}}}
def ReadFinishedJobLog(infile, status=""):#{{{
    dt = {}
    if not os.path.exists(infile):
        return dt

    hdl = myfunc.ReadLineByBlock(infile)
    if not hdl.failure:
        lines = hdl.readlines()
        while lines != None:
            for line in lines:
                if not line or line[0] == "#":
                    continue
                strs = line.split("\t")
                if len(strs)>= 10:
                    jobid = strs[0]
                    status_this_job = strs[1]
                    if status == "" or status == status_this_job:
                        jobname = strs[2]
                        ip = strs[3]
                        email = strs[4]
                        try:
                            numseq = int(strs[5])
                        except:
                            numseq = 1
                        method_submission = strs[6]
                        submit_date_str = strs[7]
                        start_date_str = strs[8]
                        finish_date_str = strs[9]
                        dt[jobid] = [status_this_job, jobname, ip, email,
                                numseq, method_submission, submit_date_str,
                                start_date_str, finish_date_str]
            lines = hdl.readlines()
        hdl.close()

    return dt
#}}}
def findjob(request):#{{{
    info = {}
    errmsg = ""
    client_ip = request.META['REMOTE_ADDR']
    username = request.user.username
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    all_logfile_query =  "%s/%s/%s"%(SITE_ROOT, "static/log", "submitted_seq.log")
    info['header'] = ["No.", "JobID","JobName", "NumSeq", "Email", "Submit date"]
    matched_list = []
    num_matched = 0
    is_form_submitted = False
    info['jobid'] = ""
    info['jobname'] = ""

    if g_params['DEBUG']:
        myfunc.WriteFile("request.method=%s\n"%(str(request.method)), gen_logfile, "a", True)
    if request.method == 'GET':
        form = SubmissionForm_findjob(request.GET)
        if request.GET.get('do'):
            is_form_submitted = True
            if g_params['DEBUG']: myfunc.WriteFile("Enter POST\n", gen_logfile, "a", True)
            if form.is_valid():
                if g_params['DEBUG']: myfunc.WriteFile("form.is_valid == True\n", gen_logfile, "a", True)
                st_jobid = request.GET.get('jobid')
                st_jobname = request.GET.get('jobname')

                matched_jobidlist = []

                if not (st_jobid or st_jobname):
                    errmsg = "Error! Neither Job ID nor Job Name is set."
                else:
                    alljob_dict = myfunc.ReadSubmittedLogFile(all_logfile_query)
                    all_jobidList = list(alljob_dict.keys())
                    all_jobnameList = [alljob_dict[x][1] for x in all_jobidList]
                    if st_jobid:
                        if  st_jobid.startswith("rst_") and len(st_jobid) >= 5:
                            for jobid in all_jobidList:
                                if jobid.find(st_jobid) != -1:
                                    matched_jobidlist.append(jobid)
                        else:
                            errmsg = "Error! Searching text for Job ID must be started with 'rst_'\
                                    and contains at least one char after 'rst_'"
                    else:
                        matched_jobidlist = all_jobidList

                    if st_jobname:
                        newli = []
                        for jobid in matched_jobidlist:
                            jobname = alljob_dict[jobid][1]
                            if jobname.find(st_jobname) != -1:
                                newli.append(jobid)
                        matched_jobidlist = newli

                num_matched = len(matched_jobidlist)
                for i in range(num_matched):
                    jobid = matched_jobidlist[i]
                    li = alljob_dict[jobid]
                    submit_date_str = li[0]
                    jobname = li[1]
                    email = li[3]
                    numseq_str = li[4]
                    rstdir = "%s/%s"%(path_result, jobid)
                    if os.path.exists(rstdir):
                        matched_list.append([i+1, jobid, jobname, numseq_str, email, submit_date_str])
    else:
        #errmsg = "Error! Neither Job ID nor Job Name is set."
        form = SubmissionForm_findjob()

    num_matched = len(matched_list)
    info['errmsg'] = errmsg
    info['form'] = form
    try:
        info['jobid'] = st_jobid
    except:
        pass

    try:
        info['jobname'] = st_jobname
    except:
        pass
    info['num_matched'] = num_matched
    info['content'] = matched_list
    info['BASEURL'] = g_params['BASEURL']
    info['is_form_submitted'] = is_form_submitted

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser, divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/findjob.html', info)
#}}}
def submit_seq(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    # if this is a POST request we need to process the form data
    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        form = SubmissionForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            # process the data in form.cleaned_data as required
            # redirect to a new URL:

            jobname = request.POST['jobname']
            email = request.POST['email']
            rawseq = request.POST['rawseq'] + "\n" # force add a new line
            Nfix = ""
            Cfix = ""
            fix_str = ""
            isForceRun = False
            try:
                Nfix = request.POST['Nfix']
            except:
                pass
            try:
                Cfix = request.POST['Cfix']
            except:
                pass
            try:
                fix_str = request.POST['fix_str']
            except:
                pass

            if 'forcerun' in request.POST:
                isForceRun = True


            try:
                seqfile = request.FILES['seqfile']
            except KeyError, MultiValueDictKeyError:
                seqfile = ""
            date_str = time.strftime(g_params['FORMAT_DATETIME'])
            query = {}
            query['rawseq'] = rawseq
            query['seqfile'] = seqfile
            query['email'] = email
            query['jobname'] = jobname
            query['date'] = date_str
            query['client_ip'] = client_ip
            query['errinfo'] = ""
            query['method_submission'] = "web"
            query['Nfix'] = Nfix
            query['Cfix'] = Cfix
            query['fix_str'] = fix_str
            query['isForceRun'] = isForceRun
            query['username'] = username

            is_valid = webserver_common.ValidateQuery(request, query, g_params)

            if is_valid:
                jobid = RunQuery(request, query)

                # type of method_submission can be web or wsdl
                #date, jobid, IP, numseq, size, jobname, email, method_submission
                log_record = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(query['date'], jobid,
                        query['client_ip'], query['numseq'],
                        len(query['rawseq']),query['jobname'], query['email'],
                        query['method_submission'])
                main_logfile_query = "%s/%s/%s"%(SITE_ROOT, "static/log", "submitted_seq.log")
                myfunc.WriteFile(log_record, main_logfile_query, "a")

                divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                        "static/log/divided", "%s_submitted_seq.log"%(client_ip))
                divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                        "static/log/divided", "%s_finished_job.log"%(client_ip))
                if client_ip != "":
                    myfunc.WriteFile(log_record, divided_logfile_query, "a")


                file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
                query['file_seq_warning'] = os.path.basename(file_seq_warning)
                if query['warninfo'] != "":
                    myfunc.WriteFile(query['warninfo'], file_seq_warning, "a")

                query['jobid'] = jobid
                query['raw_query_seqfile'] = "query.raw.fa"
                query['BASEURL'] = g_params['BASEURL']

                # start the qd_fe if not, in the background
#                 cmd = [qd_fe_scriptfile]
                base_www_url = "http://" + request.META['HTTP_HOST']
                # run the daemon only at the frontend
                if webserver_common.IsFrontEndNode(base_www_url):
                    cmd = "nohup %s %s &"%(python_exec, qd_fe_scriptfile)
                    os.system(cmd)


                if query['numseq'] < 0: #go to result page anyway
                    query['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
                            divided_logfile_query, divided_logfile_finished_jobid)
                    return render(request, 'pred/thanks.html', query)
                else:
                    return get_results(request, jobid)

            else:
                query['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
                        divided_logfile_query, divided_logfile_finished_jobid)
                return render(request, 'pred/badquery.html', query)

    # if a GET (or any other method) we'll create a blank form
    else:
        form = SubmissionForm()

    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    jobcounter = GetJobCounter(client_ip, isSuperUser, divided_logfile_query,
            divided_logfile_finished_jobid)
    info['form'] = form
    info['jobcounter'] = jobcounter
    return render(request, 'pred/submit_seq.html', info)
#}}}

def login(request):#{{{
    #logout(request)
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser, divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/login.html', info)
#}}}
def WaitForResult(jobid, MAX_WAIT_TIME=2):#{{{
# if the running time is shorter than MAX_WAIT_TIME seconds, go directly to the
# result page, other wise, show the link information
    finishtagfile = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "runjob.finish")

    cnt_time = 0
    interval = 0.1
    while 1:
        if not os.path.exists(finishtagfile):
            time.sleep(interval)
            cnt_time += interval
        else:
            break
        if cnt_time > MAX_WAIT_TIME:
            break
#}}}
def GetJobCounter(client_ip, isSuperUser, logfile_query, #{{{
        logfile_finished_jobid):
# get job counter for the client_ip
# get the table from runlog, 
# for queued or running jobs, if source=web and numseq=1, check again the tag file in
# each individual folder, since they are queued locally
    jobcounter = {}

    jobcounter['queued'] = 0
    jobcounter['running'] = 0
    jobcounter['finished'] = 0
    jobcounter['failed'] = 0
    jobcounter['nojobfolder'] = 0 #of which the folder jobid does not exist

    jobcounter['queued_idlist'] = []
    jobcounter['running_idlist'] = []
    jobcounter['finished_idlist'] = []
    jobcounter['failed_idlist'] = []
    jobcounter['nojobfolder_idlist'] = []


    if isSuperUser:
        maxdaystoshow = g_params['BIG_NUMBER']
    else:
        maxdaystoshow = g_params['MAX_DAYS_TO_SHOW']


    hdl = myfunc.ReadLineByBlock(logfile_query)
    if hdl.failure:
        return jobcounter
    else:
        finished_job_dict = ReadFinishedJobLog(logfile_finished_jobid)
        finished_jobid_set = set([])
        failed_jobid_set = set([])
        for jobid in finished_job_dict:
            status = finished_job_dict[jobid][0]
            rstdir = "%s/%s"%(path_result, jobid)
            if status == "Finished":
                finished_jobid_set.add(jobid)
            elif status == "Failed":
                failed_jobid_set.add(jobid)
        lines = hdl.readlines()
        current_time = datetime.now(timezone(TZ))
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 7:
                    continue
                ip = strs[2]
                if not isSuperUser and ip != client_ip:
                    continue

                submit_date_str = strs[0]
                isValidSubmitDate = True
                try:
                    submit_date = webserver_common.datetime_str_to_time(submit_date_str)
                except ValueError:
                    isValidSubmitDate = False

                if not isValidSubmitDate:
                    continue

                diff_date = current_time - submit_date
                if diff_date.days > maxdaystoshow:
                    continue
                jobid = strs[1]
                rstdir = "%s/%s"%(path_result, jobid)

                if jobid in finished_jobid_set:
                    jobcounter['finished'] += 1
                    jobcounter['finished_idlist'].append(jobid)
                elif jobid in failed_jobid_set:
                    jobcounter['failed'] += 1
                    jobcounter['failed_idlist'].append(jobid)
                else:
                    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
                    failtagfile = "%s/%s"%(rstdir, "runjob.failed")
                    starttagfile = "%s/%s"%(rstdir, "runjob.start")
                    if not os.path.exists(rstdir):
                        jobcounter['nojobfolder'] += 1
                        jobcounter['nojobfolder_idlist'].append(jobid)
                    elif os.path.exists(failtagfile):
                        jobcounter['failed'] += 1
                        jobcounter['failed_idlist'].append(jobid)
                    elif os.path.exists(finishtagfile):
                        jobcounter['finished'] += 1
                        jobcounter['finished_idlist'].append(jobid)
                    elif os.path.exists(starttagfile):
                        jobcounter['running'] += 1
                        jobcounter['running_idlist'].append(jobid)
                    else:
                        jobcounter['queued'] += 1
                        jobcounter['queued_idlist'].append(jobid)
            lines = hdl.readlines()
        hdl.close()
    return jobcounter
#}}}
def GetNumSameUserInQueue(rstdir, host_ip, email):#{{{
    numseq_this_user = 1
    logfile = "%s/runjob.log"%(rstdir)
    cmd = [suq_exec, "-b", suq_basedir, "ls"]
    cmdline = " ".join(cmd)
    myfunc.WriteFile("cmdline: " + cmdline +"\n", logfile, "a")
    try:
        suq_ls_content =  myfunc.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, e:
        myfunc.WriteFile(str(e) +"\n", logfile, "a")
        return numseq_this_user

    if email != "" or host_ip != "":
        lines = suq_ls_content.split("\n")
        for line in lines:
            if ((email != "" and line.find(email) != -1) or
                (host_ip != "" and line.find(host_ip) != -1)):
                numseq_this_user += 1

    return numseq_this_user
#}}}

def RunQuery(request, query):#{{{
    errmsg = []
    tmpdir = tempfile.mkdtemp(prefix="%s/static/tmp/tmp_"%(SITE_ROOT))
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(tmpdir, 0755)
    os.chmod(rstdir, 0755)
    jobid = os.path.basename(rstdir)
    query['jobid'] = jobid

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_t = "%s/query.fa"%(tmpdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    warnfile = "%s/warn.txt"%(tmpdir)
    logfile = "%s/runjob.log"%(rstdir)

    myfunc.WriteFile("tmpdir = %s\n"%(tmpdir), logfile, "a")

    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(query['date'], jobid,
            query['client_ip'], query['numseq'],
            len(query['rawseq']),query['jobname'], query['email'],
            query['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    errmsg.append(myfunc.WriteFile(query['rawseq'], rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(query['filtered_seq'], seqfile_t, "w"))
    errmsg.append(myfunc.WriteFile(query['filtered_seq'], seqfile_r, "w"))
    base_www_url = "http://" + request.META['HTTP_HOST']
    query['base_www_url'] = base_www_url


    # for single sequence job submitted via web interface, submit to local
    # queue
    if query['numseq'] <= 0: #not jobs are submitted to the front-end server, this value can be set to 1 if single sequence jobs submitted via web interface will be run on the front end
        query['numseq_this_user'] = 1
        SubmitQueryToLocalQueue(query, tmpdir, rstdir, isOnlyGetCache=False)
    else: #all other jobs are submitted to the frontend with isOnlyGetCache=True
        query['numseq_this_user'] = 1
        SubmitQueryToLocalQueue(query, tmpdir, rstdir, isOnlyGetCache=True)


    forceruntagfile = "%s/forcerun"%(rstdir)
    if query['isForceRun']:
        myfunc.WriteFile("", forceruntagfile)
    return jobid
#}}}
def RunQuery_wsdl(rawseq, filtered_seq, seqinfo):#{{{
    errmsg = []
    tmpdir = tempfile.mkdtemp(prefix="%s/static/tmp/tmp_"%(SITE_ROOT))
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(tmpdir, 0755)
    os.chmod(rstdir, 0755)
    jobid = os.path.basename(rstdir)
    seqinfo['jobid'] = jobid
    numseq = seqinfo['numseq']

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_t = "%s/query.fa"%(tmpdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    warnfile = "%s/warn.txt"%(tmpdir)
    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
            seqinfo['client_ip'], seqinfo['numseq'],
            len(rawseq),seqinfo['jobname'], seqinfo['email'],
            seqinfo['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    errmsg.append(myfunc.WriteFile(rawseq, rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_t, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_r, "w"))
    base_www_url = "http://" + seqinfo['hostname']
    seqinfo['base_www_url'] = base_www_url

    seqinfo['numseq_this_user'] = 1
    SubmitQueryToLocalQueue(seqinfo, tmpdir, rstdir, isOnlyGetCache=True)

    # changed 2015-03-26, any jobs submitted via wsdl is hadndel
    return jobid
#}}}
def RunQuery_wsdl_local(rawseq, filtered_seq, seqinfo):#{{{
# submit the wsdl job to the local queue
    errmsg = []
    tmpdir = tempfile.mkdtemp(prefix="%s/static/tmp/tmp_"%(SITE_ROOT))
    rstdir = tempfile.mkdtemp(prefix="%s/static/result/rst_"%(SITE_ROOT))
    os.chmod(tmpdir, 0755)
    os.chmod(rstdir, 0755)
    jobid = os.path.basename(rstdir)
    seqinfo['jobid'] = jobid
    numseq = seqinfo['numseq']

# write files for the query
    jobinfofile = "%s/jobinfo"%(rstdir)
    rawseqfile = "%s/query.raw.fa"%(rstdir)
    seqfile_t = "%s/query.fa"%(tmpdir)
    seqfile_r = "%s/query.fa"%(rstdir)
    warnfile = "%s/warn.txt"%(tmpdir)
    jobinfo_str = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
            seqinfo['client_ip'], seqinfo['numseq'],
            len(rawseq),seqinfo['jobname'], seqinfo['email'],
            seqinfo['method_submission'])
    errmsg.append(myfunc.WriteFile(jobinfo_str, jobinfofile, "w"))
    errmsg.append(myfunc.WriteFile(rawseq, rawseqfile, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_t, "w"))
    errmsg.append(myfunc.WriteFile(filtered_seq, seqfile_r, "w"))
    base_www_url = "http://" + seqinfo['hostname']
    seqinfo['base_www_url'] = base_www_url

    rtvalue = SubmitQueryToLocalQueue(seqinfo, tmpdir, rstdir, isOnlyGetCache=False)
    if rtvalue != 0:
        return ""
    else:
        return jobid
#}}}
def SubmitQueryToLocalQueue(query, tmpdir, rstdir, isOnlyGetCache=False):#{{{
    scriptfile = "%s/app/submit_job_to_queue.py"%(SITE_ROOT)
    rstdir = "%s/%s"%(path_result, query['jobid'])
    debugfile = "%s/debug.log"%(rstdir) #this log only for debugging
    runjob_logfile = "%s/runjob.log"%(rstdir)
    runjob_errfile = "%s/runjob.err"%(rstdir)
    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
    rmsg = ""

    cmd = [python_exec, scriptfile, "-nseq", "%d"%query['numseq'], "-nseq-this-user",
            "%d"%query['numseq_this_user'], "-jobid", query['jobid'],
            "-outpath", rstdir, "-datapath", tmpdir, "-baseurl",
            query['base_www_url'] ]
    if query['email'] != "":
        cmd += ["-email", query['email']]
    if query['client_ip'] != "":
        cmd += ["-host", query['client_ip']]
    if query['isForceRun']:
        cmd += ["-force"]
    if isOnlyGetCache:
        cmd += ["-only-get-cache"]

    (isSuccess, t_runtime) = webserver_common.RunCmd(cmd, runjob_logfile, runjob_errfile)
    if not isSuccess:
        webserver_common.WriteDateTimeTagFile(failedtagfile, runjob_logfile, runjob_errfile)
        return 1
    else:
        return 0

#}}}

def thanks(request):#{{{
    #print "request.POST at thanks:", request.POST
    return HttpResponse("Thanks")
#}}}

def get_queue(request):#{{{
    errfile = "%s/server.err"%(path_result)

    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    status = "Queued"
    if isSuperUser:
        info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "Email", "Host", "QueueTime","RunTime", "Date", "Source"]
    else:
        info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "Email", "QueueTime","RunTime", "Date", "Source"]

    hdl = myfunc.ReadLineByBlock(divided_logfile_query)
    if hdl.failure:
        info['errmsg'] = ""
        pass
    else:
        finished_jobid_list = []
        if os.path.exists(divided_logfile_finished_jobid):
            finished_jobid_list = myfunc.ReadIDList2(divided_logfile_finished_jobid, 0, None)
        finished_jobid_set = set(finished_jobid_list)
        jobRecordList = []
        lines = hdl.readlines()
        current_time = datetime.now(timezone(TZ))
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 7:
                    continue
                ip = strs[2]
                if not isSuperUser and ip != client_ip:
                    continue
                jobid = strs[1]
                if jobid in finished_jobid_set:
                    continue

                rstdir = "%s/%s"%(path_result, jobid)
                starttagfile = "%s/%s"%(rstdir, "runjob.start")
                failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
                finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
                if (os.path.exists(rstdir) and 
                        not os.path.exists(starttagfile) and
                        not os.path.exists(failedtagfile) and
                        not os.path.exists(finishtagfile)):
                    jobRecordList.append(jobid)
            lines = hdl.readlines()
        hdl.close()

        jobid_inqueue_list = []
        rank = 0
        for jobid in jobRecordList:
            rank += 1
            ip =  ""
            jobname = ""
            email = ""
            method_submission = "web"
            numseq = 1
            rstdir = "%s/%s"%(path_result, jobid)

            submit_date_str = ""
            finish_date_str = ""
            start_date_str = ""

            jobinfofile = "%s/jobinfo"%(rstdir)
            jobinfo = myfunc.ReadFile(jobinfofile).strip()
            jobinfolist = jobinfo.split("\t")
            if len(jobinfolist) >= 8:
                submit_date_str = jobinfolist[0]
                ip = jobinfolist[2]
                numseq = int(jobinfolist[3])
                jobname = jobinfolist[5]
                email = jobinfolist[6]
                method_submission = jobinfolist[7]

            starttagfile = "%s/runjob.start"%(rstdir)
            queuetime = ""
            runtime = ""
            isValidSubmitDate = True
            try:
                submit_date = webserver_common.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False

            if isValidSubmitDate:
                queuetime = myfunc.date_diff(submit_date, current_time)

            if isSuperUser:
                jobid_inqueue_list.append([rank, jobid, jobname[:20],
                    numseq, email, ip, queuetime, runtime,
                    submit_date_str, method_submission])
            else:
                jobid_inqueue_list.append([rank, jobid, jobname[:20],
                    numseq, email, queuetime, runtime,
                    submit_date_str, method_submission])


        info['BASEURL'] = g_params['BASEURL']
        info['content'] = jobid_inqueue_list

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/queue.html', info)
#}}}
def get_running(request):#{{{
    # Get running jobs
    errfile = "%s/server.err"%(path_result)

    status = "Running"

    info = {}

    client_ip = request.META['REMOTE_ADDR']
    username = request.user.username
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    hdl = myfunc.ReadLineByBlock(divided_logfile_query)
    if hdl.failure:
        info['errmsg'] = ""
        pass
    else:
        finished_jobid_list = []
        if os.path.exists(divided_logfile_finished_jobid):
            finished_jobid_list = myfunc.ReadIDList2(divided_logfile_finished_jobid, 0, None)
        finished_jobid_set = set(finished_jobid_list)
        jobRecordList = []
        lines = hdl.readlines()
        current_time = datetime.now(timezone(TZ))
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 7:
                    continue
                ip = strs[2]
                if not isSuperUser and ip != client_ip:
                    continue
                jobid = strs[1]
                if jobid in finished_jobid_set:
                    continue
                rstdir = "%s/%s"%(path_result, jobid)
                starttagfile = "%s/%s"%(rstdir, "runjob.start")
                finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
                failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
                if (os.path.exists(rstdir) and os.path.exists(starttagfile) and (not
                    os.path.exists(finishtagfile) and not
                    os.path.exists(failedtagfile))):
                    jobRecordList.append(jobid)
            lines = hdl.readlines()
        hdl.close()

        jobid_inqueue_list = []
        rank = 0
        for jobid in jobRecordList:
            rank += 1
            ip =  ""
            jobname = ""
            email = ""
            method_submission = "web"
            numseq = 1
            rstdir = "%s/%s"%(path_result, jobid)

            submit_date_str = ""
            finish_date_str = ""
            start_date_str = ""


            jobinfofile = "%s/jobinfo"%(rstdir)
            jobinfo = myfunc.ReadFile(jobinfofile).strip()
            jobinfolist = jobinfo.split("\t")
            if len(jobinfolist) >= 8:
                submit_date_str = jobinfolist[0]
                ip = jobinfolist[2]
                numseq = int(jobinfolist[3])
                jobname = jobinfolist[5]
                email = jobinfolist[6]
                method_submission = jobinfolist[7]

            finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
            numFinishedSeq = 0
            if os.path.exists(finished_idx_file):
                finished_idxlist = myfunc.ReadIDList(finished_idx_file)
                numFinishedSeq = len(set(finished_idxlist))

            starttagfile = "%s/runjob.start"%(rstdir)
            queuetime = ""
            runtime = ""
            isValidSubmitDate = True
            isValidStartDate = True
            try:
                submit_date = webserver_common.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False
            start_date_str = ""
            if os.path.exists(starttagfile):
                start_date_str = myfunc.ReadFile(starttagfile).strip()
            try:
                start_date =  webserver_common.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            if isValidStartDate:
                runtime = myfunc.date_diff(start_date, current_time)
            if isValidStartDate and isValidSubmitDate:
                queuetime = myfunc.date_diff(submit_date, start_date)

            if isSuperUser:
                jobid_inqueue_list.append([rank, jobid, jobname[:20],
                    numseq, numFinishedSeq, email, ip, queuetime, runtime,
                    submit_date_str, method_submission])
            else:
                jobid_inqueue_list.append([rank, jobid, jobname[:20],
                    numseq, numFinishedSeq, email, queuetime, runtime,
                    submit_date_str, method_submission])


        info['BASEURL'] = g_params['BASEURL']
        if info['isSuperUser']:
            info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "NumFinished", "Email", "Host", "QueueTime","RunTime", "Date", "Source"]
        else:
            info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "NumFinished", "Email", "QueueTime","RunTime", "Date", "Source"]
        info['content'] = jobid_inqueue_list

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser, divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/running.html', info)
#}}}
def get_finished_job(request):#{{{
    info = {}
    info['BASEURL'] = g_params['BASEURL']


    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    if isSuperUser:
        maxdaystoshow = g_params['BIG_NUMBER']
        info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "Email", "Host", "QueueTime","RunTime", "Date", "Source"]
    else:
        maxdaystoshow = g_params['MAX_DAYS_TO_SHOW']
        info['header'] = ["No.", "JobID","JobName", "NumSeq",
                "Email", "QueueTime","RunTime", "Date", "Source"]

    info['MAX_DAYS_TO_SHOW'] = maxdaystoshow

    hdl = myfunc.ReadLineByBlock(divided_logfile_query)
    if hdl.failure:
        #info['errmsg'] = "Failed to retrieve finished job information!"
        info['errmsg'] = ""
        pass
    else:
        finished_job_dict = ReadFinishedJobLog(divided_logfile_finished_jobid)
        jobRecordList = []
        lines = hdl.readlines()
        current_time = datetime.now(timezone(TZ))
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 7:
                    continue
                ip = strs[2]
                if not isSuperUser and ip != client_ip:
                    continue

                submit_date_str = strs[0]
                isValidSubmitDate = True
                try:
                    submit_date = webserver_common.datetime_str_to_time(submit_date_str)
                except ValueError:
                    isValidSubmitDate = False
                if not isValidSubmitDate:
                    continue

                diff_date = current_time - submit_date
                if diff_date.days > maxdaystoshow:
                    continue
                jobid = strs[1]
                rstdir = "%s/%s"%(path_result, jobid)
                if jobid in finished_job_dict:
                    status = finished_job_dict[jobid][0]
                    if status == "Finished":
                        jobRecordList.append(jobid)
                else:
                    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
                    failedtagfile = "%s/%s"%(rstdir, "runjob.failed")
                    if (os.path.exists(rstdir) and  os.path.exists(finishtagfile) and
                            not os.path.exists(failedtagfile)):
                        jobRecordList.append(jobid)
            lines = hdl.readlines()
        hdl.close()

        finished_job_info_list = []
        rank = 0
        for jobid in jobRecordList:
            rank += 1
            ip =  ""
            jobname = ""
            email = ""
            method_submission = "web"
            numseq = 1
            rstdir = "%s/%s"%(path_result, jobid)
            starttagfile = "%s/runjob.start"%(rstdir)
            finishtagfile = "%s/runjob.finish"%(rstdir)

            submit_date_str = ""
            finish_date_str = ""
            start_date_str = ""

            if jobid in finished_job_dict:
                status = finished_job_dict[jobid][0]
                jobname = finished_job_dict[jobid][1]
                ip = finished_job_dict[jobid][2]
                email = finished_job_dict[jobid][3]
                numseq = finished_job_dict[jobid][4]
                method_submission = finished_job_dict[jobid][5]
                submit_date_str = finished_job_dict[jobid][6]
                start_date_str = finished_job_dict[jobid][7]
                finish_date_str = finished_job_dict[jobid][8]
            else:
                jobinfofile = "%s/jobinfo"%(rstdir)
                jobinfo = myfunc.ReadFile(jobinfofile).strip()
                jobinfolist = jobinfo.split("\t")
                if len(jobinfolist) >= 8:
                    submit_date_str = jobinfolist[0]
                    numseq = int(jobinfolist[3])
                    jobname = jobinfolist[5]
                    email = jobinfolist[6]
                    method_submission = jobinfolist[7]

            isValidSubmitDate = True
            isValidStartDate = True
            isValidFinishDate = True
            try:
                submit_date = webserver_common.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False
            start_date_str = ""
            if os.path.exists(starttagfile):
                start_date_str = myfunc.ReadFile(starttagfile).strip()
            try:
                start_date = webserver_common.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            finish_date_str = myfunc.ReadFile(finishtagfile).strip()
            try:
                finish_date = webserver_common.datetime_str_to_time(finish_date_str)
            except ValueError:
                isValidFinishDate = False

            queuetime = ""
            runtime = ""

            if isValidStartDate and isValidFinishDate:
                runtime = myfunc.date_diff(start_date, finish_date)
            if isValidSubmitDate and isValidStartDate:
                queuetime = myfunc.date_diff(submit_date, start_date)

            if info['isSuperUser']:
                finished_job_info_list.append([rank, jobid, jobname[:20],
                    str(numseq), email, ip, queuetime, runtime, submit_date_str,
                    method_submission])
            else:
                finished_job_info_list.append([rank, jobid, jobname[:20],
                    str(numseq), email, queuetime, runtime, submit_date_str,
                    method_submission])

        info['content'] = finished_job_info_list

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/finished_job.html', info)

#}}}
def get_failed_job(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "failed_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_failed_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip


    if isSuperUser:
        maxdaystoshow = g_params['BIG_NUMBER']
        info['header'] = ["No.", "JobID","JobName", "NumSeq", "Email",
                "Host", "QueueTime","RunTime", "Date", "Source"]
    else:
        maxdaystoshow = g_params['MAX_DAYS_TO_SHOW']
        info['header'] = ["No.", "JobID","JobName", "NumSeq", "Email",
                "QueueTime","RunTime", "Date", "Source"]


    info['MAX_DAYS_TO_SHOW'] = maxdaystoshow
    info['BASEURL'] = g_params['BASEURL']

    hdl = myfunc.ReadLineByBlock(divided_logfile_query)
    if hdl.failure:
#         info['errmsg'] = "Failed to retrieve finished job information!"
        info['errmsg'] = ""
        pass
    else:
        finished_job_dict = ReadFinishedJobLog(divided_logfile_finished_jobid)
        jobRecordList = []
        lines = hdl.readlines()
        current_time = datetime.now(timezone(TZ))
        while lines != None:
            for line in lines:
                strs = line.split("\t")
                if len(strs) < 7:
                    continue
                ip = strs[2]
                if not isSuperUser and ip != client_ip:
                    continue

                submit_date_str = strs[0]
                submit_date = webserver_common.datetime_str_to_time(submit_date_str)
                diff_date = current_time - submit_date
                if diff_date.days > maxdaystoshow:
                    continue
                jobid = strs[1]
                rstdir = "%s/%s"%(path_result, jobid)

                if jobid in finished_job_dict:
                    status = finished_job_dict[jobid][0]
                    if status == "Failed":
                        jobRecordList.append(jobid)
                else:
                    failtagfile = "%s/%s"%(rstdir, "runjob.failed")
                    if os.path.exists(rstdir) and os.path.exists(failtagfile):
                        jobRecordList.append(jobid)
            lines = hdl.readlines()
        hdl.close()


        failed_job_info_list = []
        rank = 0
        for jobid in jobRecordList:
            rank += 1

            ip = ""
            jobname = ""
            email = ""
            method_submission = ""
            numseq = 1
            submit_date_str = ""

            rstdir = "%s/%s"%(path_result, jobid)
            starttagfile = "%s/runjob.start"%(rstdir)
            failtagfile = "%s/runjob.failed"%(rstdir)

            if jobid in finished_job_dict:
                submit_date_str = finished_job_dict[jobid][0]
                jobname = finished_job_dict[jobid][1]
                ip = finished_job_dict[jobid][2]
                email = finished_job_dict[jobid][3]
                numseq = finished_job_dict[jobid][4]
                method_submission = finished_job_dict[jobid][5]
                submit_date_str = finished_job_dict[jobid][6]
                start_date_str = finished_job_dict[jobid][ 7]
                finish_date_str = finished_job_dict[jobid][8]
            else:
                jobinfofile = "%s/jobinfo"%(rstdir)
                jobinfo = myfunc.ReadFile(jobinfofile).strip()
                jobinfolist = jobinfo.split("\t")
                if len(jobinfolist) >= 8:
                    submit_date_str = jobinfolist[0]
                    numseq = int(jobinfolist[3])
                    jobname = jobinfolist[5]
                    email = jobinfolist[6]
                    method_submission = jobinfolist[7]


            isValidStartDate = True
            isValidFailedDate = True
            isValidSubmitDate = True

            try:
                submit_date = webserver_common.datetime_str_to_time(submit_date_str)
            except ValueError:
                isValidSubmitDate = False

            start_date_str = ""
            if os.path.exists(starttagfile):
                start_date_str = myfunc.ReadFile(starttagfile).strip()
            try:
                start_date = webserver_common.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            failed_date_str = myfunc.ReadFile(failtagfile).strip()
            try:
                failed_date = webserver_common.datetime_str_to_time(failed_date_str)
            except ValueError:
                isValidFailedDate = False

            queuetime = ""
            runtime = ""

            if isValidStartDate and isValidFailedDate:
                runtime = myfunc.date_diff(start_date, failed_date)
            if isValidSubmitDate and isValidStartDate:
                queuetime = myfunc.date_diff(submit_date, start_date)

            if info['isSuperUser']:
                failed_job_info_list.append([rank, jobid, jobname[:20],
                    str(numseq), email, ip, queuetime, runtime, submit_date_str,
                    method_submission])
            else:
                failed_job_info_list.append([rank, jobid, jobname[:20],
                    str(numseq), email, queuetime, runtime, submit_date_str,
                    method_submission])


        info['content'] = failed_job_info_list

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/failed_job.html', info)
#}}}

def search(request):#{{{
    if 'q' in request.GET and request.GET['q']:
        q = request.GET['q']
        seq = Query.objects.filter(seqname=q)
        return render(request, 'search_results.html',
            {'seq': seq, 'query': q})
    else:
        return HttpResponse('Please submit a search term.')
#}}}
def get_help(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/help.html', info)
#}}}
def get_countjob_country(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    countjob_by_country = "%s/countjob_by_country.txt"%(path_stat)
    lines = myfunc.ReadFile(countjob_by_country).split("\n")
    li_countjob_country = []
    for line in lines: 
        if not line or line[0]=="#":
            continue
        strs = line.split("\t")
        if len(strs) >= 4:
            country = strs[0]
            try:
                numseq = int(strs[1])
            except:
                numseq = 0
            try:
                numjob = int(strs[2])
            except:
                numjob = 0
            try:
                numip = int(strs[3])
            except:
                numip = 0
            li_countjob_country.append([country, numseq, numjob, numip])
    li_countjob_country_header = ["Country", "Numseq", "Numjob", "NumIP"]

    info['li_countjob_country'] = li_countjob_country
    info['li_countjob_country_header'] = li_countjob_country_header
    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/countjob_country.html', info)
#}}}
def get_news(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    newsfile = "%s/%s/%s"%(SITE_ROOT, "static/doc", "news.txt")
    newsList = []
    if os.path.exists(newsfile):
        newsList = myfunc.ReadNews(newsfile)
    info['newsList'] = newsList
    info['newsfile'] = newsfile

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/news.html', info)
#}}}
def get_reference(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/reference.html', info)
#}}}
def get_serverstatus(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    logfile_finished =  "%s/%s/%s"%(SITE_ROOT, "static/log", "finished_job.log")
    logfile_runjob =  "%s/%s/%s"%(SITE_ROOT, "static/log", "runjob_log.log")
    logfile_country_job = "%s/%s/%s"%(path_log, "stat", "country_job_numseq.txt")

# finished sequences submitted by wsdl
# finished sequences submitted by web

# javascript to show finished sequences of the data (histogram)

# get jobs queued locally (at the front end)
    num_seq_in_local_queue = 0
    cmd = [suq_exec, "-b", suq_basedir, "ls"]
    cmdline = " ".join(cmd)
    try:
        suq_ls_content =  myfunc.check_output(cmd, stderr=subprocess.STDOUT)
        lines = suq_ls_content.split("\n")
        cntjob = 0
        for line in lines:
            if line.find("runjob") != -1:
                cntjob += 1
        num_seq_in_local_queue = cntjob
    except subprocess.CalledProcessError, e:
        date_str = time.strftime(g_params['FORMAT_DATETIME'])
        myfunc.WriteFile("[%s] %s\n"%(date_str, str(e)), gen_errfile, "a", True)

# get jobs queued remotely ()
    runjob_dict = {}
    if os.path.exists(logfile_runjob):
        runjob_dict = myfunc.ReadRunJobLog(logfile_runjob)
    cntseq_in_remote_queue = 0
    for jobid in runjob_dict:
        li = runjob_dict[jobid]
        numseq = li[4]
        rstdir = "%s/%s"%(path_result, jobid)
        finished_idx_file = "%s/finished_seqindex.txt"%(rstdir)
        if os.path.exists(finished_idx_file):
            num_finished = len(myfunc.ReadIDList(finished_idx_file))
        else:
            num_finished = 0

        cntseq_in_remote_queue += (numseq - num_finished)



# get number of finished seqs
    allfinishedjoblogfile = "%s/all_finished_job.log"%(path_log)
    allfinished_job_dict = {}
    user_dict = {} # by IP
    if os.path.exists(allfinishedjoblogfile):
        allfinished_job_dict = myfunc.ReadFinishedJobLog(allfinishedjoblogfile)
    total_num_finished_seq = 0
    numjob_wed = 0
    numjob_wsdl = 0
    startdate = ""
    submitdatelist = []
    iplist = []
    countrylist = []
    for jobid in allfinished_job_dict:
        li = allfinished_job_dict[jobid]
        try:
            numseq = int(li[4])
        except:
            numseq = 1
        try:
            submitdatelist.append(li[6])
        except:
            pass
        try:
            method_submission = li[5]
        except:
            method_submission = ""
        try:
            iplist.append(li[2])
        except:
            pass
        ip = ""
        try:
            ip = li[2]
        except:
            pass


        if method_submission == "web":
            numjob_wed += 1
        elif method_submission == "wsdl":
            numjob_wsdl += 1

        if ip != "" and ip != "All" and ip != "127.0.0.1":

            if not ip in user_dict:
                user_dict[ip] = [0,0] #[num_job, num_seq]
            user_dict[ip][0] += 1
            user_dict[ip][1] += numseq

        total_num_finished_seq += numseq

    submitdatelist = sorted(submitdatelist, reverse=False)
    if len(submitdatelist)>0:
        startdate = submitdatelist[0].split()[0]

    uniq_iplist = list(set(iplist))

    countjob_by_country = "%s/countjob_by_country.txt"%(path_stat)
    lines = myfunc.ReadFile(countjob_by_country).split("\n")
    li_countjob_country = []
    countrylist = []
    for line in lines: 
        if not line or line[0]=="#":
            continue
        strs = line.split("\t")
        if len(strs) >= 4:
            country = strs[0]
            try:
                numseq = int(strs[1])
            except:
                numseq = 0
            try:
                numjob = int(strs[2])
            except:
                numjob = 0
            try:
                numip = int(strs[3])
            except:
                numip = 0
            li_countjob_country.append([country, numseq, numjob, numip])
            countrylist.append(country)
    uniq_countrylist = list(set(countrylist))

    li_countjob_country_header = ["Country", "Numseq", "Numjob", "NumIP"]


    MAX_ACTIVE_USER = 10
    # get most active users by num_job
    activeuserli_njob_header = ["IP", "Country", "NumJob", "NumSeq"]
    activeuserli_njob = []
    rawlist = sorted(user_dict.items(), key=lambda x:x[1][0], reverse=True)
    cnt = 0
    for i in xrange(len(rawlist)):
        cnt += 1
        ip = rawlist[i][0]
        njob = rawlist[i][1][0]
        nseq = rawlist[i][1][1]
        country = "N/A"
        try:
            match = geolite2.lookup(ip)
            country = pycountry.countries.get(alpha_2=match.country).name
        except:
            pass
        activeuserli_njob.append([ip, country, njob, nseq])
        if cnt >= MAX_ACTIVE_USER:
            break

    # get most active users by num_seq
    activeuserli_nseq_header = ["IP", "Country", "NumJob", "NumSeq"]
    activeuserli_nseq = []
    rawlist = sorted(user_dict.items(), key=lambda x:x[1][1], reverse=True)
    cnt = 0
    for i in xrange(len(rawlist)):
        cnt += 1
        ip = rawlist[i][0]
        njob = rawlist[i][1][0]
        nseq = rawlist[i][1][1]
        country = "N/A"
        try:
            match = geolite2.lookup(ip)
            country = pycountry.countries.get(alpha_2=match.country).name
        except:
            pass
        activeuserli_nseq.append([ip, country, njob, nseq])
        if cnt >= MAX_ACTIVE_USER:
            break

# get longest predicted seq
# get query with most TM helics
# get query takes the longest time
    extreme_runtimelogfile = "%s/stat/extreme_jobruntime.log"%(path_log)
    runtimelogfile = "%s/jobruntime.log"%(path_log)
    infile_runtime = runtimelogfile
    if os.path.exists(extreme_runtimelogfile) and os.path.getsize(extreme_runtimelogfile):
        infile_runtime = extreme_runtimelogfile

    li_longestseq = []
    li_mostTM = []
    li_longestruntime = []
    longestlength = -1
    mostTM = -1
    longestruntime = -1.0

    hdl = myfunc.ReadLineByBlock(infile_runtime)
    if not hdl.failure:
        lines = hdl.readlines()
        while lines != None:
            for line in lines:
                strs = line.split()
                if len(strs) < 8:
                    continue
                runtime = -1.0
                jobid = strs[0]
                seqidx = strs[1]
                try:
                    runtime = float(strs[3])
                except:
                    pass
                numTM = -1
                try:
                    numTM = int(strs[6])
                except:
                    pass
                mtd_profile = strs[4]
                lengthseq = -1
                try:
                    lengthseq = int(strs[5])
                except:
                    pass
                if runtime > longestruntime:
                    li_longestruntime = [jobid, seqidx, runtime, lengthseq, numTM]
                    longestruntime = runtime
                if lengthseq > longestlength:
                    li_longestseq = [jobid, seqidx, runtime, lengthseq, numTM]
                    longestlength = lengthseq
                if numTM > mostTM:
                    mostTM = numTM
                    li_mostTM = [jobid, seqidx, runtime, lengthseq, numTM]
            lines = hdl.readlines()
        hdl.close()

    info['longestruntime_str'] = myfunc.second_to_human(int(longestruntime+0.5))
    info['mostTM_str'] = str(mostTM)
    info['longestlength_str'] = str(longestlength)
    info['total_num_finished_seq'] = total_num_finished_seq
    info['total_num_finished_job'] = len(allfinished_job_dict)
    info['num_unique_ip'] = len(uniq_iplist)
    info['num_unique_country'] = len(uniq_countrylist)
    info['num_finished_seqs_str'] = str(info['total_num_finished_seq'])
    info['num_finished_jobs_str'] = str(info['total_num_finished_job'])
    info['num_finished_jobs_web_str'] = str(numjob_wed)
    info['num_finished_jobs_wsdl_str'] = str(numjob_wsdl)
    info['num_unique_ip_str'] = str(info['num_unique_ip'])
    info['num_unique_country_str'] = str(info['num_unique_country'])
    info['num_seq_in_local_queue'] = num_seq_in_local_queue
    info['num_seq_in_remote_queue'] = cntseq_in_remote_queue
    info['activeuserli_nseq_header'] = activeuserli_nseq_header
    info['activeuserli_njob_header'] = activeuserli_njob_header
    info['li_countjob_country_header'] = li_countjob_country_header
    info['li_countjob_country'] = li_countjob_country
    info['activeuserli_njob_header'] = activeuserli_njob_header
    info['activeuserli_nseq'] = activeuserli_nseq
    info['activeuserli_njob'] = activeuserli_njob
    info['li_longestruntime'] = li_longestruntime
    info['li_longestseq'] = li_longestseq
    info['li_mostTM'] = li_mostTM

    info['startdate'] = startdate
    info['BASEURL'] = g_params['BASEURL']
    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)


    return render(request, 'pred/serverstatus.html', info)
#}}}
def get_example(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/example.html', info)
#}}}
def oldtopcons(request):#{{{
    url_oldtopcons = "http://old.topcons.net"
    return HttpResponseRedirect(url_oldtopcons);
#}}}
def help_wsdl_api(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip


    api_script_rtname =  "subcons_wsdl"
    extlist = [".py"]
    api_script_lang_list = ["Python"]
    api_script_info_list = []

    for i in xrange(len(extlist)):
        ext = extlist[i]
        api_script_file = "%s/%s/%s"%(SITE_ROOT,
                "static/download/script", "%s%s"%(api_script_rtname,
                    ext))
        api_script_basename = os.path.basename(api_script_file)
        if not os.path.exists(api_script_file):
            continue
        cmd = [api_script_file, "-h"]
        try:
            usage = myfunc.check_output(cmd)
        except subprocess.CalledProcessError, e:
            usage = ""
        api_script_info_list.append([api_script_lang_list[i], api_script_basename, usage])

    info['api_script_info_list'] = api_script_info_list
    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/help_wsdl_api.html', info)
#}}}
def download(request):#{{{
    info = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    info['username'] = username
    info['isSuperUser'] = isSuperUser
    info['client_ip'] = client_ip
    info['zipfile_wholepackage'] = ""
    info['zipfile_database'] = ""
    info['size_wholepackage'] = ""
    info['size_database'] = ""
    size_wholepackage = 0
    zipfile_wholepackage = "%s/%s/%s"%(SITE_ROOT, "static/download", "topcons2.0_Linux_x64_with_database.zip")
    zipfile_database = "%s/%s/%s"%(SITE_ROOT, "static/download", "topcons2_database.zip")
    if os.path.exists(zipfile_wholepackage):
        info['zipfile_wholepackage'] = os.path.basename(zipfile_wholepackage)
        size_wholepackage = os.path.getsize(os.path.realpath(zipfile_wholepackage))
        size_wholepackage_str = myfunc.Size_byte2human(size_wholepackage)
        info['size_wholepackage'] = size_wholepackage_str
    if os.path.exists(zipfile_database):
        info['zipfile_database'] = os.path.basename(zipfile_database)
        size_database = os.path.getsize(os.path.realpath(zipfile_database))
        size_database_str = myfunc.Size_byte2human(size_database)
        info['size_database'] = size_database_str

    info['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)

    return render(request, 'pred/download.html', info)
#}}}

def get_results(request, jobid="1"):#{{{
    resultdict = {}

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    resultdict['username'] = username
    resultdict['isSuperUser'] = isSuperUser
    resultdict['client_ip'] = client_ip


    #img1 = "%s/%s/%s/%s"%(SITE_ROOT, "result", jobid, "PconsC2.s400.jpg")
    #url_img1 =  serve(request, os.path.basename(img1), os.path.dirname(img1))
    rstdir = "%s/%s"%(path_result, jobid)
    outpathname = jobid
    resultfile = "%s/%s/%s/%s"%(rstdir, jobid, outpathname, "query.result.txt")
    tarball = "%s/%s.tar.gz"%(rstdir, outpathname)
    zipfile = "%s/%s.zip"%(rstdir, outpathname)
    starttagfile = "%s/%s"%(rstdir, "runjob.start")
    finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
    failtagfile = "%s/%s"%(rstdir, "runjob.failed")
    errfile = "%s/%s"%(rstdir, "runjob.err")
    query_seqfile = "%s/%s"%(rstdir, "query.fa")
    raw_query_seqfile = "%s/%s"%(rstdir, "query.raw.fa")
    seqid_index_mapfile = "%s/%s/%s"%(rstdir,jobid, "seqid_index_map.txt")
    finished_seq_file = "%s/%s/finished_seqs.txt"%(rstdir, jobid)
    statfile = "%s/%s/stat.txt"%(rstdir, jobid)
    method_submission = "web"

    jobinfofile = "%s/jobinfo"%(rstdir)
    jobinfo = myfunc.ReadFile(jobinfofile).strip()
    jobinfolist = jobinfo.split("\t")
    if len(jobinfolist) >= 8:
        submit_date_str = jobinfolist[0]
        numseq = int(jobinfolist[3])
        jobname = jobinfolist[5]
        email = jobinfolist[6]
        method_submission = jobinfolist[7]
    else:
        submit_date_str = ""
        numseq = 1
        jobname = ""
        email = ""
        method_submission = "web"

    isValidSubmitDate = True
    try:
        submit_date = webserver_common.datetime_str_to_time(submit_date_str)
    except ValueError:
        isValidSubmitDate = False
    current_time = datetime.now(timezone(TZ))

    resultdict['isResultFolderExist'] = True
    resultdict['errinfo'] = ""
    if os.path.exists(errfile):
        resultdict['errinfo'] = myfunc.ReadFile(errfile)

    status = ""
    queuetime = ""
    runtime = ""
    queuetime_in_sec = 0
    runtime_in_sec = 0
    if not os.path.exists(rstdir):
        resultdict['isResultFolderExist'] = False
        resultdict['isFinished'] = False
        resultdict['isFailed'] = True
        resultdict['isStarted'] = False
    elif os.path.exists(failtagfile):
        resultdict['isFinished'] = False
        resultdict['isFailed'] = True
        resultdict['isStarted'] = True
        status = "Failed"
        start_date_str = ""
        if os.path.exists(starttagfile):
            start_date_str = myfunc.ReadFile(starttagfile).strip()
        isValidStartDate = True
        isValidFailedDate = True
        try:
            start_date = webserver_common.datetime_str_to_time(start_date_str)
        except ValueError:
            isValidStartDate = False
        failed_date_str = myfunc.ReadFile(failtagfile).strip()
        try:
            failed_date = webserver_common.datetime_str_to_time(failed_date_str)
        except ValueError:
            isValidFailedDate = False
        if isValidSubmitDate and isValidStartDate:
            queuetime = myfunc.date_diff(submit_date, start_date)
            queuetime_in_sec = (start_date - submit_date).total_seconds()
        if isValidStartDate and isValidFailedDate:
            runtime = myfunc.date_diff(start_date, failed_date)
            runtime_in_sec = (failed_date - start_date).total_seconds()
    else:
        resultdict['isFailed'] = False
        if os.path.exists(finishtagfile):
            resultdict['isFinished'] = True
            resultdict['isStarted'] = True
            status = "Finished"
            isValidStartDate = True
            isValidFinishDate = True
            if os.path.exists(starttagfile):
                start_date_str = myfunc.ReadFile(starttagfile).strip()
            else:
                start_date_str = ""
            try:
                start_date = webserver_common.datetime_str_to_time(start_date_str)
            except ValueError:
                isValidStartDate = False
            finish_date_str = myfunc.ReadFile(finishtagfile).strip()
            try:
                finish_date = webserver_common.datetime_str_to_time(finish_date_str)
            except ValueError:
                isValidFinishDate = False
            if isValidSubmitDate and isValidStartDate:
                queuetime = myfunc.date_diff(submit_date, start_date)
                queuetime_in_sec = (start_date - submit_date).total_seconds()
            if isValidStartDate and isValidFinishDate:
                runtime = myfunc.date_diff(start_date, finish_date)
                runtime_in_sec = (finish_date - start_date).total_seconds()
        else:
            resultdict['isFinished'] = False
            if os.path.exists(starttagfile):
                isValidStartDate = True
                start_date_str = ""
                if os.path.exists(starttagfile):
                    start_date_str = myfunc.ReadFile(starttagfile).strip()
                try:
                    start_date = webserver_common.datetime_str_to_time(start_date_str)
                except ValueError:
                    isValidStartDate = False
                resultdict['isStarted'] = True
                status = "Running"
                if isValidSubmitDate and isValidStartDate:
                    queuetime = myfunc.date_diff(submit_date, start_date)
                    queuetime_in_sec = (start_date - submit_date).total_seconds()
                if isValidStartDate:
                    runtime = myfunc.date_diff(start_date, current_time)
                    runtime_in_sec = (current_time - start_date).total_seconds()
            else:
                resultdict['isStarted'] = False
                status = "Wait"
                if isValidSubmitDate:
                    queuetime = myfunc.date_diff(submit_date, current_time)
                    queuetime_in_sec = (current_time - submit_date).total_seconds()

    color_status = SetColorStatus(status)

    file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
    seqwarninfo = ""
    if os.path.exists(file_seq_warning):
        seqwarninfo = myfunc.ReadFile(file_seq_warning)
        seqwarninfo = seqwarninfo.strip()

    resultdict['file_seq_warning'] = os.path.basename(file_seq_warning)
    resultdict['seqwarninfo'] = seqwarninfo
    resultdict['jobid'] = jobid
    resultdict['subdirname'] = "seq_0"
    resultdict['jobname'] = jobname
    resultdict['outpathname'] = os.path.basename(outpathname)
    resultdict['resultfile'] = os.path.basename(resultfile)
    resultdict['tarball'] = os.path.basename(tarball)
    resultdict['zipfile'] = os.path.basename(zipfile)
    resultdict['submit_date'] = submit_date_str
    resultdict['queuetime'] = queuetime
    resultdict['runtime'] = runtime
    resultdict['BASEURL'] = g_params['BASEURL']
    resultdict['status'] = status
    resultdict['color_status'] = color_status
    resultdict['numseq'] = numseq
    resultdict['query_seqfile'] = os.path.basename(query_seqfile)
    resultdict['raw_query_seqfile'] = os.path.basename(raw_query_seqfile)
    base_www_url = "http://" + request.META['HTTP_HOST']
#   note that here one must add http:// in front of the url
    resultdict['url_result'] = "%s/pred/result/%s"%(base_www_url, jobid)

    sum_run_time = 0.0
    average_run_time = float(g_params['AVERAGE_RUNTIME_PER_SEQ_IN_SEC'])  # default average_run_time
    num_finished = 0
    cntnewrun = 0
    cntcached = 0
    newrun_table_list = [] # this is used for calculating the remaining time
# get seqid_index_map
    if os.path.exists(finished_seq_file):
        resultdict['index_table_header'] = ["No.", "Length", "LOC_DEF", "LOC_DEF_SCORE",
                "RunTime(s)", "SequenceName", "Source", "FinishDate" ]
        index_table_content_list = []
        indexmap_content = myfunc.ReadFile(finished_seq_file).split("\n")
        cnt = 0
        for line in indexmap_content:
            strs = line.split("\t")
            if len(strs)>=7:
                subfolder = strs[0]
                length_str = strs[1]
                loc_def_str = strs[2]
                loc_def_score_str = strs[3]
                source = strs[4]
                try:
                    finishdate = strs[7]
                except IndexError:
                    finishdate = "N/A"

                try:
                    runtime_in_sec_str = "%.1f"%(float(strs[5]))
                    if source == "newrun":
                        sum_run_time += float(strs[5])
                        cntnewrun += 1
                    elif source == "cached":
                        cntcached += 1
                except:
                    runtime_in_sec_str = ""
                desp = strs[6]
                rank = "%d"%(cnt+1)
                if cnt < g_params['MAX_ROWS_TO_SHOW_IN_TABLE']:
                    index_table_content_list.append([rank, length_str, loc_def_str,
                        loc_def_score_str, runtime_in_sec_str, desp[:30], subfolder, source, finishdate])
                if source == "newrun":
                    newrun_table_list.append([rank, subfolder])
                cnt += 1
        if cntnewrun > 0:
            average_run_time = sum_run_time / float(cntnewrun)

        resultdict['index_table_content_list'] = index_table_content_list
        resultdict['indexfiletype'] = "finishedfile"
        resultdict['num_finished'] = cnt
        num_finished = cnt
        resultdict['percent_finished'] = "%.1f"%(float(cnt)/numseq*100)
    else:
        resultdict['index_table_header'] = []
        resultdict['index_table_content_list'] = []
        resultdict['indexfiletype'] = "finishedfile"
        resultdict['num_finished'] = 0
        resultdict['percent_finished'] = "%.1f"%(0.0)

    num_remain = numseq - num_finished
    time_remain_in_sec = num_remain * average_run_time # set default value

    resultdict['num_row_result_table'] = len(resultdict['index_table_content_list'])

    # calculate the remaining time based on the average_runtime of the last x
    # number of newrun sequences

    avg_newrun_time = webserver_common.GetAverageNewRunTime(finished_seq_file, window=10)

    if cntnewrun > 0 and avg_newrun_time >= 0:
        time_remain_in_sec = int(avg_newrun_time*num_remain+0.5)

    time_remain = myfunc.second_to_human(time_remain_in_sec)
    resultdict['time_remain'] = time_remain
    qdinittagfile = "%s/runjob.qdinit"%(rstdir)

    if os.path.exists(rstdir):
        resultdict['isResultFolderExist'] = True
    else:
        resultdict['isResultFolderExist'] = False

    if numseq <= 1:
        resultdict['refresh_interval'] = webserver_common.GetRefreshInterval(
                queuetime_in_sec, runtime_in_sec, method_submission)
        #debug
        date_str = time.strftime(g_params['FORMAT_DATETIME'])
        msg = "queuetime_in_sec = %d, runtime_in_sec = %d"%(queuetime_in_sec, runtime_in_sec)
        myfunc.WriteFile("[%s] %s\n"%(date_str, msg), gen_logfile, "a", True)
    else:
        if os.path.exists(qdinittagfile):
            addtime = int(math.sqrt(max(0,min(num_remain, num_finished))))+1
            resultdict['refresh_interval'] = average_run_time + addtime
        else:
            resultdict['refresh_interval'] = webserver_common.GetRefreshInterval(
                    queuetime_in_sec, runtime_in_sec, method_submission)

    # get stat info
    if os.path.exists(statfile):#{{{
        content = myfunc.ReadFile(statfile)
        lines = content.split("\n")
        for line in lines:
            strs = line.split()
            if len(strs) >= 2:
                resultdict[strs[0]] = strs[1]
                percent =  "%.1f"%(int(strs[1])/float(numseq)*100)
                newkey = strs[0].replace('num_', 'per_')
                resultdict[newkey] = percent
#}}}
    resultdict['MAX_ROWS_TO_SHOW_IN_TABLE'] = g_params['MAX_ROWS_TO_SHOW_IN_TABLE']
    resultdict['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/get_results.html', resultdict)
#}}}
def get_results_eachseq(request, jobid="1", seqindex="1"):#{{{
    resultdict = {}

    resultdict['isAllNonTM'] = True

    username = request.user.username
    client_ip = request.META['REMOTE_ADDR']
    if username in settings.SUPER_USER_LIST:
        isSuperUser = True
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "submitted_seq.log")
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log", "finished_job.log")
    else:
        isSuperUser = False
        divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_submitted_seq.log"%(client_ip))
        divided_logfile_finished_jobid =  "%s/%s/%s"%(SITE_ROOT,
                "static/log/divided", "%s_finished_job.log"%(client_ip))

    resultdict['username'] = username
    resultdict['isSuperUser'] = isSuperUser
    resultdict['client_ip'] = client_ip

    rstdir = "%s/%s"%(path_result, jobid)
    outpathname = jobid

    jobinfofile = "%s/jobinfo"%(rstdir)
    jobinfo = myfunc.ReadFile(jobinfofile).strip()
    jobinfolist = jobinfo.split("\t")
    if len(jobinfolist) >= 8:
        submit_date_str = jobinfolist[0]
        numseq = int(jobinfolist[3])
        jobname = jobinfolist[5]
        email = jobinfolist[6]
        method_submission = jobinfolist[7]
    else:
        submit_date_str = ""
        numseq = 1
        jobname = ""
        email = ""
        method_submission = "web"

    status = ""

    resultdict['jobid'] = jobid
    resultdict['subdirname'] = seqindex
    resultdict['jobname'] = jobname
    resultdict['outpathname'] = os.path.basename(outpathname)
    resultdict['BASEURL'] = g_params['BASEURL']
    resultdict['status'] = status
    resultdict['numseq'] = numseq
    base_www_url = "http://" + request.META['HTTP_HOST']

    resultfile = "%s/%s/%s/%s"%(rstdir, outpathname, seqindex, "query.result.txt")
    htmlfigure_file =  "%s/%s/%s/plot/%s"%(rstdir, outpathname, seqindex, "query_0.html")
    if os.path.exists(htmlfigure_file):
        resultdict['htmlfigure'] = "%s/%s/%s/%s/plot/%s"%(
                "result", jobid, jobid, seqindex,
                os.path.basename(htmlfigure_file))
    else:
        resultdict['htmlfigure'] = ""

    if os.path.exists(rstdir):
        resultdict['isResultFolderExist'] = True
    else:
        resultdict['isResultFolderExist'] = False


    if os.path.exists(resultfile):
        resultdict['resultfile'] = os.path.basename(resultfile)
    else:
        resultdict['resultfile'] = ""

    resultdict['jobcounter'] = GetJobCounter(client_ip, isSuperUser,
            divided_logfile_query, divided_logfile_finished_jobid)
    return render(request, 'pred/get_results_eachseq.html', resultdict)
#}}}


def my_view(request):#{{{
    # loop through keys
    for key in request.POST:
        value = request.POST[key]
    # loop through keys and values
    for key, value in request.POST.iteritems():
        print key, value
#}}}
def search_form(request):#{{{
    return render(request, 'pred/search_form.html')
#}}}
# enabling wsdl service

#{{{ The actual wsdl api
class Container_submitseq(DjangoComplexModel):
    class Attributes(DjangoComplexModel.Attributes):
        django_model = FieldContainer
        django_exclude = ['excluded_field']


class Service_submitseq(ServiceBase):
    @rpc(Unicode,  Unicode, Unicode, Unicode,  _returns=Iterable(Unicode))
# submit job to the front-end
    def submitjob(ctx, seq="", fixtop="", jobname="", email=""):#{{{
        seq = seq + "\n" #force add a new line for correct parsing the fasta file
        seqinfo = {}
        filtered_seq = webserver_common.ValidateSeq(seq, seqinfo, g_params)
        # ValidateFixtop(fixtop) #to be implemented
        jobid = "None"
        url = "None"
        numseq_str = "%d"%(seqinfo['numseq'])
        warninfo = seqinfo['warninfo']
        errinfo = ""
#         print "\n\nreq\n", dir(ctx.transport.req) #debug
#         print "\n\n", ctx.transport.req.META['REMOTE_ADDR'] #debug
#         print "\n\n", ctx.transport.req.META['HTTP_HOST']   #debug
        if filtered_seq == "":
            errinfo = seqinfo['errinfo']
        else:
            soap_req = ctx.transport.req
            try:
                client_ip = soap_req.META['REMOTE_ADDR']
            except:
                client_ip = ""

            try:
                hostname = soap_req.META['HTTP_HOST']
            except:
                hostname = ""
#             print client_ip
#             print hostname
            seqinfo['jobname'] = jobname
            seqinfo['email'] = email
            seqinfo['fixtop'] = fixtop
            seqinfo['date'] = time.strftime(g_params['FORMAT_DATETIME'])
            seqinfo['client_ip'] = client_ip
            seqinfo['hostname'] = hostname
            seqinfo['method_submission'] = "wsdl"
            seqinfo['isForceRun'] = False  # disable isForceRun if submitted by WSDL
            jobid = RunQuery_wsdl(seq, filtered_seq, seqinfo)
            if jobid == "":
                errinfo = "Failed to submit your job to the queue\n"+seqinfo['errinfo']
            else:
                log_record = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
                        seqinfo['client_ip'], seqinfo['numseq'],
                        len(seq),seqinfo['jobname'], seqinfo['email'],
                        seqinfo['method_submission'])
                main_logfile_query = "%s/%s/%s"%(SITE_ROOT, "static/log", "submitted_seq.log")
                myfunc.WriteFile(log_record, main_logfile_query, "a")

                divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT, "static/log/divided",
                        "%s_submitted_seq.log"%(seqinfo['client_ip']))
                if seqinfo['client_ip'] != "":
                    myfunc.WriteFile(log_record, divided_logfile_query, "a")

                url = "http://" + hostname + g_params['BASEURL'] + "result/%s"%(jobid)

                file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
                if seqinfo['warninfo'] != "":
                    myfunc.WriteFile(seqinfo['warninfo'], file_seq_warning, "a")
                errinfo = seqinfo['errinfo']

        for s in [jobid, url, numseq_str, errinfo, warninfo]:
            yield s
#}}}

    @rpc(Unicode,  Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Iterable(Unicode))
# submitted_remote will be called by the daemon
# sequences are submitted one by one by the daemon, but the numseq_of_job is
# for the number of sequences of the whole job submitted to the front end
# isforcerun is set as string, "true" or "false", case insensitive
    def submitjob_remote(ctx, seq="", fixtop="", jobname="", email="",#{{{
            numseq_this_user="", isforcerun=""):
        seq = seq + "\n" #force add a new line for correct parsing the fasta file
        seqinfo = {}
        filtered_seq = webserver_common.ValidateSeq(seq, seqinfo, g_params)
        # ValidateFixtop(fixtop) #to be implemented
        if numseq_this_user != "" and numseq_this_user.isdigit():
            seqinfo['numseq_this_user'] = int(numseq_this_user)
        else:
            seqinfo['numseq_this_user'] = 1

        numseq_str = "%d"%(seqinfo['numseq'])
        warninfo = seqinfo['warninfo']
#         print "\n\nreq\n", dir(ctx.transport.req) #debug
#         print "\n\n", ctx.transport.req.META['REMOTE_ADDR'] #debug
#         print "\n\n", ctx.transport.req.META['HTTP_HOST']   #debug
        jobid = "None"
        url = "None"
        if filtered_seq == "":
            errinfo = seqinfo['errinfo']
        else:
            soap_req = ctx.transport.req
            try:
                client_ip = soap_req.META['REMOTE_ADDR']
            except:
                client_ip = ""

            try:
                hostname = soap_req.META['HTTP_HOST']
            except:
                hostname = ""
#             print client_ip
#             print hostname
            seqinfo['jobname'] = jobname
            seqinfo['email'] = email
            seqinfo['fixtop'] = fixtop
            seqinfo['date'] = time.strftime(g_params['FORMAT_DATETIME'])
            seqinfo['client_ip'] = client_ip
            seqinfo['hostname'] = hostname
            seqinfo['method_submission'] = "wsdl"
            # for this method, wsdl is called only by the daemon script, isForceRun can be
            # set by the argument
            if isforcerun.upper()[:1] == "T":
                seqinfo['isForceRun'] = True
            else:
                seqinfo['isForceRun'] = False
            jobid = RunQuery_wsdl_local(seq, filtered_seq, seqinfo)
            if jobid == "":
                errinfo = "Failed to submit your job to the queue\n"+seqinfo['errinfo']
            else:
                log_record = "%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n"%(seqinfo['date'], jobid,
                        seqinfo['client_ip'], seqinfo['numseq'],
                        len(seq),seqinfo['jobname'], seqinfo['email'],
                        seqinfo['method_submission'])
                main_logfile_query = "%s/%s/%s"%(SITE_ROOT, "static/log", "submitted_seq.log")
                myfunc.WriteFile(log_record, main_logfile_query, "a")

                divided_logfile_query =  "%s/%s/%s"%(SITE_ROOT, "static/log/divided",
                        "%s_submitted_seq.log"%(seqinfo['client_ip']))
                if seqinfo['client_ip'] != "":
                    myfunc.WriteFile(log_record, divided_logfile_query, "a")

                url = "http://" + hostname + g_params['BASEURL'] + "result/%s"%(jobid)

                file_seq_warning = "%s/%s/%s/%s"%(SITE_ROOT, "static/result", jobid, "query.warn.txt")
                if seqinfo['warninfo'] != "":
                    myfunc.WriteFile(seqinfo['warninfo'], file_seq_warning, "a")
                errinfo = seqinfo['errinfo']

        for s in [jobid, url, numseq_str, errinfo, warninfo]:
            yield s
#}}}

    @rpc(Unicode, _returns=Iterable(Unicode))
    def checkjob(ctx, jobid=""):#{{{
        rstdir = "%s/%s"%(path_result, jobid)
        soap_req = ctx.transport.req
        hostname = soap_req.META['HTTP_HOST']
        result_url = "http://" + hostname + "/static/" + "result/%s/%s.zip"%(jobid, jobid)
        status = "None"
        url = ""
        errinfo = ""
        if not os.path.exists(rstdir):
            status = "None"
            errinfo = "Error! jobid %s does not exist."%(jobid)
        else:
            starttagfile = "%s/%s"%(rstdir, "runjob.start")
            finishtagfile = "%s/%s"%(rstdir, "runjob.finish")
            failtagfile = "%s/%s"%(rstdir, "runjob.failed")
            errfile = "%s/%s"%(rstdir, "runjob.err")
            if os.path.exists(failtagfile):
                status = "Failed"
                errinfo = ""
                if os.path.exists(errfile):
                    errinfo = myfunc.ReadFile(errfile)
            elif os.path.exists(finishtagfile):
                status = "Finished"
                url = result_url
                errinfo = ""
            elif os.path.exists(starttagfile):
                status = "Running"
            else:
                status = "Wait"
        for s in [status, url, errinfo]:
            yield s
#}}}
    @rpc(Unicode, _returns=Iterable(Unicode))
    def deletejob(ctx, jobid=""):#{{{
        rstdir = "%s/%s"%(path_result, jobid)
        status = "None"
        errinfo = ""
        try: 
            shutil.rmtree(rstdir)
            status = "Succeeded"
        except OSError as e:
            errinfo = str(e)
            status = "Failed"
        for s in [status, errinfo]:
            yield s
#}}}

class ContainerService_submitseq(ServiceBase):
    @rpc(Integer, _returns=Container_submitseq)
    def get_container(ctx, pk):
        try:
            return FieldContainer.objects.get(pk=pk)
        except FieldContainer.DoesNotExist:
            raise ResourceNotFoundError('Container_submitseq')

    @rpc(Container_submitseq, _returns=Container_submitseq)
    def create_container(ctx, container):
        try:
            return FieldContainer.objects.create(**container.as_dict())
        except IntegrityError:
            raise ResourceAlreadyExistsError('Container_submitseq')

class ExceptionHandlingService_submitseq(DjangoServiceBase):
    """Service for testing exception handling."""

    @rpc(_returns=Container_submitseq)
    def raise_does_not_exist(ctx):
        return FieldContainer.objects.get(pk=-1)

    @rpc(_returns=Container_submitseq)
    def raise_validation_error(ctx):
        raise ValidationError('Is not valid.')


app_submitseq = Application([Service_submitseq, ContainerService_submitseq,
    ExceptionHandlingService_submitseq], 'v2.topcons.net',
    in_protocol=Soap11(validator='soft'), out_protocol=Soap11())
#wsgi_app_submitseq = WsgiApplication(app_submitseq)

submitseq_service = csrf_exempt(DjangoApplication(app_submitseq))

#}}}
