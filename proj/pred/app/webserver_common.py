#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Description:
#   A collection of classes and functions used by web-servers
#
# Author: Nanjiang Shu (nanjiang.shu@scilifelab.se)
#
# Address: Science for Life Laboratory Stockholm, Box 1031, 17121 Solna, Sweden

import os
import sys
import myfunc
rundir = os.path.dirname(os.path.realpath(__file__))
from datetime import datetime
from dateutil import parser as dtparser
from pytz import timezone
import time
import tabulate
import subprocess
import re
import logging
import shutil
import sqlite3
FORMAT_DATETIME = "%Y-%m-%d %H:%M:%S %Z"
TZ = "Europe/Stockholm"
def WriteSubconsTextResultFile(outfile, outpath_result, maplist,#{{{
        runtime_in_sec, base_www_url, statfile=""):
    try:
        fpout = open(outfile, "w")
        if statfile != "":
            fpstat = open(statfile, "w")

        date_str = time.strftime(FORMAT_DATETIME)
        print >> fpout, "##############################################################################"
        print >> fpout, "Subcons result file"
        print >> fpout, "Generated from %s at %s"%(base_www_url, date_str)
        print >> fpout, "Total request time: %.1f seconds."%(runtime_in_sec)
        print >> fpout, "##############################################################################"
        cnt = 0
        for line in maplist:
            strs = line.split('\t')
            subfoldername = strs[0]
            length = int(strs[1])
            desp = strs[2]
            seq = strs[3]
            seqid = myfunc.GetSeqIDFromAnnotation(desp)
            print >> fpout, "Sequence number: %d"%(cnt+1)
            print >> fpout, "Sequence name: %s"%(desp)
            print >> fpout, "Sequence length: %d aa."%(length)
            print >> fpout, "Sequence:\n%s\n\n"%(seq)

            rstfile1 = "%s/%s/%s/query_0_final.csv"%(outpath_result, subfoldername, "plot")
            rstfile2 = "%s/%s/query_0_final.csv"%(outpath_result, subfoldername)
            if os.path.exists(rstfile1):
                rstfile = rstfile1
            elif os.path.exists(rstfile2):
                rstfile = rstfile2
            else:
                rstfile = ""

            if os.path.exists(rstfile):
                content = myfunc.ReadFile(rstfile).strip()
                lines = content.split("\n")
                if len(lines) >= 6:
                    header_line = lines[0].split("\t")
                    if header_line[0].strip() == "":
                        header_line[0] = "Method"
                        header_line = [x.strip() for x in header_line]

                    data_line = []
                    for i in xrange(1, len(lines)):
                        strs1 = lines[i].split("\t")
                        strs1 = [x.strip() for x in strs1]
                        data_line.append(strs1)

                    content = tabulate.tabulate(data_line, header_line, 'plain')
            else:
                content = ""
            if content == "":
                content = "***No prediction could be produced with this method***"

            print >> fpout, "Prediction results:\n\n%s\n\n"%(content)

            print >> fpout, "##############################################################################"
            cnt += 1

    except IOError:
        print "Failed to write to file %s"%(outfile)
#}}}
def ReplaceDescriptionSingleFastaFile(infile, new_desp):#{{{
    """Replace the description line of the fasta file by the new_desp
    """
    if os.path.exists(infile):
        (seqid, seqanno, seq) = myfunc.ReadSingleFasta(infile)
        if seqanno != new_desp:
            myfunc.WriteFile(">%s\n%s\n"%(new_desp, seq), infile)
        return 0
    else:
        sys.stderr.write("infile %s does not exists at %s\n"%(infile, sys._getframe().f_code.co_name))
        return 1
#}}}

def GetLocDef(predfile):#{{{
    """Read in LocDef and its corresponding score from the subcons prediction file
    """
    content = ""
    if os.path.exists(predfile):
        content = myfunc.ReadFile(predfile)

    loc_def = None
    loc_def_score = None
    if content != "":
        lines = content.split("\n")
        if len(lines)>=2:
            strs0 = lines[0].split("\t")
            strs1 = lines[1].split("\t")
            strs0 = [x.strip() for x in strs0]
            strs1 = [x.strip() for x in strs1]
            if len(strs0) == len(strs1) and len(strs0) > 2:
                if strs0[1] == "LOC_DEF":
                    loc_def = strs1[1]
                    dt_score = {}
                    for i in xrange(2, len(strs0)):
                        dt_score[strs0[i]] = strs1[i]
                    if loc_def in dt_score:
                        loc_def_score = dt_score[loc_def]

    return (loc_def, loc_def_score)
#}}}
def IsFrontEndNode(base_www_url):#{{{
    """
    check if the base_www_url is front-end node
    if base_www_url is ip address, then not the front-end
    otherwise yes
    """
    base_www_url = base_www_url.lstrip("http://").lstrip("https://").split("/")[0]
    if base_www_url == "":
        return False
    elif base_www_url.find("computenode") != -1:
        return False
    else:
        arr =  [x.isdigit() for x in base_www_url.split('.')]
        if all(arr):
            return False
        else:
            return True
#}}}

def GetAverageNewRunTime(finished_seq_file, window=100):#{{{
    """Get average running time of the newrun tasks for the last x number of
sequences
    """
    logger = logging.getLogger(__name__)
    avg_newrun_time = -1.0
    if not os.path.exists(finished_seq_file):
        return avg_newrun_time
    else:
        indexmap_content = myfunc.ReadFile(finished_seq_file).split("\n")
        indexmap_content = indexmap_content[::-1]
        cnt = 0
        sum_run_time = 0.0
        for line in indexmap_content:
            strs = line.split("\t")
            if len(strs)>=7:
                source = strs[4]
                if source == "newrun":
                    try:
                        sum_run_time += float(strs[5])
                        cnt += 1
                    except:
                        logger.debug("bad format in finished_seq_file (%s) with line \"%s\""%(finished_seq_file, line))
                        pass

                if cnt >= window:
                    break

        if cnt > 0:
            avg_newrun_time = sum_run_time/float(cnt)
        return avg_newrun_time


#}}}
def ValidateQuery(request, query, g_params):#{{{
    query['errinfo_br'] = ""
    query['errinfo_content'] = ""
    query['warninfo'] = ""

    has_pasted_seq = False
    has_upload_file = False
    if query['rawseq'].strip() != "":
        has_pasted_seq = True
    if query['seqfile'] != "":
        has_upload_file = True

    if has_pasted_seq and has_upload_file:
        query['errinfo_br'] += "Confused input!"
        query['errinfo_content'] = "You should input your query by either "\
                "paste the sequence in the text area or upload a file."
        return False
    elif not has_pasted_seq and not has_upload_file:
        query['errinfo_br'] += "No input!"
        query['errinfo_content'] = "You should input your query by either "\
                "paste the sequence in the text area or upload a file "
        return False
    elif query['seqfile'] != "":
        try:
            fp = request.FILES['seqfile']
            fp.seek(0,2)
            filesize = fp.tell()
            if filesize > g_params['MAXSIZE_UPLOAD_FILE_IN_BYTE']:
                query['errinfo_br'] += "Size of uploaded file exceeds limit!"
                query['errinfo_content'] += "The file you uploaded exceeds "\
                        "the upper limit %g Mb. Please split your file and "\
                        "upload again."%(g_params['MAXSIZE_UPLOAD_FILE_IN_MB'])
                return False

            fp.seek(0,0)
            content = fp.read()
        except KeyError:
            query['errinfo_br'] += ""
            query['errinfo_content'] += """
            Failed to read uploaded file \"%s\"
            """%(query['seqfile'])
            return False
        query['rawseq'] = content

    query['filtered_seq'] = ValidateSeq(query['rawseq'], query, g_params)
    is_valid = query['isValidSeq']
    return is_valid
#}}}
def ValidateSeq(rawseq, seqinfo, g_params):#{{{
# seq is the chunk of fasta file
# seqinfo is a dictionary
# return (filtered_seq)
    rawseq = re.sub(r'[^\x00-\x7f]',r' ',rawseq) # remove non-ASCII characters
    rawseq = re.sub(r'[\x0b]',r' ',rawseq) # filter invalid characters for XML
    filtered_seq = ""
    # initialization
    for item in ['errinfo_br', 'errinfo', 'errinfo_content', 'warninfo']:
        if item not in seqinfo:
            seqinfo[item] = ""

    seqinfo['isValidSeq'] = True

    seqRecordList = []
    myfunc.ReadFastaFromBuffer(rawseq, seqRecordList, True, 0, 0)
# filter empty sequences and any sequeces shorter than MIN_LEN_SEQ or longer
# than MAX_LEN_SEQ
    newSeqRecordList = []
    li_warn_info = []
    isHasEmptySeq = False
    isHasShortSeq = False
    isHasLongSeq = False
    isHasDNASeq = False
    cnt = 0
    for rd in seqRecordList:
        seq = rd[2].strip()
        seqid = rd[0].strip()
        if len(seq) == 0:
            isHasEmptySeq = 1
            msg = "Empty sequence %s (SeqNo. %d) is removed."%(seqid, cnt+1)
            li_warn_info.append(msg)
        elif len(seq) < g_params['MIN_LEN_SEQ']:
            isHasShortSeq = 1
            msg = "Sequence %s (SeqNo. %d) is removed since its length is < %d."%(seqid, cnt+1, g_params['MIN_LEN_SEQ'])
            li_warn_info.append(msg)
        elif len(seq) > g_params['MAX_LEN_SEQ']:
            isHasLongSeq = True
            msg = "Sequence %s (SeqNo. %d) is removed since its length is > %d."%(seqid, cnt+1, g_params['MAX_LEN_SEQ'])
            li_warn_info.append(msg)
        elif myfunc.IsDNASeq(seq):
            isHasDNASeq = True
            msg = "Sequence %s (SeqNo. %d) is removed since it looks like a DNA sequence."%(seqid, cnt+1)
            li_warn_info.append(msg)
        else:
            newSeqRecordList.append(rd)
        cnt += 1
    seqRecordList = newSeqRecordList

    numseq = len(seqRecordList)

    if numseq < 1:
        seqinfo['errinfo_br'] += "Number of input sequences is 0!\n"
        t_rawseq = rawseq.lstrip()
        if t_rawseq and t_rawseq[0] != '>':
            seqinfo['errinfo_content'] += "Bad input format. The FASTA format should have an annotation line start with '>'.\n"
        if len(li_warn_info) >0:
            seqinfo['errinfo_content'] += "\n".join(li_warn_info) + "\n"
        if not isHasShortSeq and not isHasEmptySeq and not isHasLongSeq and not isHasDNASeq:
            seqinfo['errinfo_content'] += "Please input your sequence in FASTA format.\n"

        seqinfo['isValidSeq'] = False
    elif numseq > g_params['MAX_NUMSEQ_PER_JOB']:
        seqinfo['errinfo_br'] += "Number of input sequences exceeds the maximum (%d)!\n"%(
                g_params['MAX_NUMSEQ_PER_JOB'])
        seqinfo['errinfo_content'] += "Your query has %d sequences. "%(numseq)
        seqinfo['errinfo_content'] += "However, the maximal allowed sequences per job is %d. "%(
                g_params['MAX_NUMSEQ_PER_JOB'])
        seqinfo['errinfo_content'] += "Please split your query into smaller files and submit again.\n"
        seqinfo['isValidSeq'] = False
    else:
        li_badseq_info = []
        if 'isForceRun' in seqinfo and seqinfo['isForceRun'] and numseq > g_params['MAX_NUMSEQ_FOR_FORCE_RUN']:
            seqinfo['errinfo_br'] += "Invalid input!"
            seqinfo['errinfo_content'] += "You have chosen the \"Force Run\" mode. "\
                    "The maximum allowable number of sequences of a job is %d. "\
                    "However, your input has %d sequences."%(g_params['MAX_NUMSEQ_FOR_FORCE_RUN'], numseq)
            seqinfo['isValidSeq'] = False


# checking for bad sequences in the query

    if seqinfo['isValidSeq']:
        for i in xrange(numseq):
            seq = seqRecordList[i][2].strip()
            anno = seqRecordList[i][1].strip().replace('\t', ' ')
            seqid = seqRecordList[i][0].strip()
            seq = seq.upper()
            seq = re.sub("[\s\n\r\t]", '', seq)
            li1 = [m.start() for m in re.finditer("[^ABCDEFGHIKLMNPQRSTUVWYZX*-]", seq)]
            if len(li1) > 0:
                for j in xrange(len(li1)):
                    msg = "Bad letter for amino acid in sequence %s (SeqNo. %d) "\
                            "at position %d (letter: '%s')"%(seqid, i+1,
                                    li1[j]+1, seq[li1[j]])
                    li_badseq_info.append(msg)

        if len(li_badseq_info) > 0:
            seqinfo['errinfo_br'] += "There are bad letters for amino acids in your query!\n"
            seqinfo['errinfo_content'] = "\n".join(li_badseq_info) + "\n"
            seqinfo['isValidSeq'] = False

# convert some non-classical letters to the standard amino acid symbols
# Scheme:
#    out of these 26 letters in the alphabet, 
#    B, Z -> X
#    U -> C
#    *, - will be deleted
    if seqinfo['isValidSeq']:
        li_newseq = []
        for i in xrange(numseq):
            seq = seqRecordList[i][2].strip()
            anno = seqRecordList[i][1].strip()
            seqid = seqRecordList[i][0].strip()
            seq = seq.upper()
            seq = re.sub("[\s\n\r\t]", '', seq)
            anno = anno.replace('\t', ' ') #replace tab by whitespace


            li1 = [m.start() for m in re.finditer("[BZ]", seq)]
            if len(li1) > 0:
                for j in xrange(len(li1)):
                    msg = "Amino acid in sequence %s (SeqNo. %d) at position %d "\
                            "(letter: '%s') has been replaced by 'X'"%(seqid,
                                    i+1, li1[j]+1, seq[li1[j]])
                    li_warn_info.append(msg)
                seq = re.sub("[BZ]", "X", seq)

            li1 = [m.start() for m in re.finditer("[U]", seq)]
            if len(li1) > 0:
                for j in xrange(len(li1)):
                    msg = "Amino acid in sequence %s (SeqNo. %d) at position %d "\
                            "(letter: '%s') has been replaced by 'C'"%(seqid,
                                    i+1, li1[j]+1, seq[li1[j]])
                    li_warn_info.append(msg)
                seq = re.sub("[U]", "C", seq)

            li1 = [m.start() for m in re.finditer("[*]", seq)]
            if len(li1) > 0:
                for j in xrange(len(li1)):
                    msg = "Translational stop in sequence %s (SeqNo. %d) at position %d "\
                            "(letter: '%s') has been deleted"%(seqid,
                                    i+1, li1[j]+1, seq[li1[j]])
                    li_warn_info.append(msg)
                seq = re.sub("[*]", "", seq)

            li1 = [m.start() for m in re.finditer("[-]", seq)]
            if len(li1) > 0:
                for j in xrange(len(li1)):
                    msg = "Gap in sequence %s (SeqNo. %d) at position %d "\
                            "(letter: '%s') has been deleted"%(seqid,
                                    i+1, li1[j]+1, seq[li1[j]])
                    li_warn_info.append(msg)
                seq = re.sub("[-]", "", seq)

            # check the sequence length again after potential removal of
            # translation stop
            if len(seq) < g_params['MIN_LEN_SEQ']:
                isHasShortSeq = 1
                msg = "Sequence %s (SeqNo. %d) is removed since its length is < %d (after removal of translation stop)."%(seqid, i+1, g_params['MIN_LEN_SEQ'])
                li_warn_info.append(msg)
            else:
                li_newseq.append(">%s\n%s"%(anno, seq))

        filtered_seq = "\n".join(li_newseq) # seq content after validation
        seqinfo['numseq'] = len(li_newseq)
        seqinfo['warninfo'] = "\n".join(li_warn_info) + "\n"

    seqinfo['errinfo'] = seqinfo['errinfo_br'] + seqinfo['errinfo_content']
    return filtered_seq
#}}}
def InsertFinishDateToDB(date_str, md5_key, seq, outdb):# {{{
    """ Insert the finish date to the sqlite3 database
    """
    tbname_content = "data"
    try:
        con = sqlite3.connect(outdb)
    except Exception as e:
        print("Failed to connect to the database outdb %s"%(outdb))
    with con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS %s
            (
                md5 TEXT PRIMARY KEY,
                seq TEXT,
                date_finish TEXT
            )"""%(tbname_content))
        cmd =  "INSERT OR REPLACE INTO %s(md5,  seq, date_finish) VALUES('%s', '%s','%s')"%(tbname_content, md5_key, seq, date_str)
        try:
            cur.execute(cmd)
            return 0
        except Exception as e:
            print >> sys.stderr, "Exception %s"%(str(e))
            return 1

# }}}
def RunCmd(cmd, logfile, errfile, verbose=False):# {{{
    """Input cmd in list
       Run the command and also output message to logs
    """
    begin_time = time.time()

    isCmdSuccess = False
    cmdline = " ".join(cmd)
    date_str = time.strftime(FORMAT_DATETIME)
    rmsg = ""
    try:
        rmsg = subprocess.check_output(cmd)
        if verbose:
            msg = "workflow: %s"%(cmdline)
            myfunc.WriteFile("[%s] %s\n"%(date_str, msg),  logfile, "a", True)
        isCmdSuccess = True
    except subprocess.CalledProcessError, e:
        msg = "cmdline: %s\nFailed with message \"%s\""%(cmdline, str(e))
        myfunc.WriteFile("[%s] %s\n"%(date_str, msg),  errfile, "a", True)
        isCmdSuccess = False
        pass

    end_time = time.time()
    runtime_in_sec = end_time - begin_time

    return (isCmdSuccess, runtime_in_sec)
# }}}
def datetime_str_to_epoch(date_str):# {{{
    """convert the date_time in string to epoch
    The string of date_time may with or without the zone info
    """
    return dtparser.parse(date_str).strftime("%s")
# }}}
def datetime_str_to_time(date_str):# {{{
    """convert the date_time in string to datetime type
    The string of date_time may with or without the zone info
    """
    strs = date_str.split()
    dt = dtparser.parse(date_str)
    if len(strs) == 2:
        dt = dt.replace(tzinfo=timezone('UTC'))
    return dt
# }}}
def GetInfoFinish_TOPCONS2(outpath_this_seq, origIndex, seqLength, seqAnno, source_result="", runtime=0.0):# {{{
    """Get the list info_finish for the method TOPCONS2"""
    topfile = "%s/%s/topcons.top"%(
            outpath_this_seq, "Topcons")
    top = myfunc.ReadFile(topfile).strip()
    numTM = myfunc.CountTM(top)
    posSP = myfunc.GetSPPosition(top)
    if len(posSP) > 0:
        isHasSP = True
    else:
        isHasSP = False
    date_str = time.strftime(FORMAT_DATETIME)
    info_finish = [ "seq_%d"%origIndex,
            str(seqLength), str(numTM),
            str(isHasSP), source_result, str(runtime),
            seqAnno.replace('\t', ' '), date_str]
    return info_finish
# }}}
def GetInfoFinish_Subcons(outpath_this_seq, origIndex, seqLength, seqAnno, source_result="", runtime=0.0):# {{{
    """Get the list info_finish for the method Subcons"""
    finalpredfile = "%s/%s/query_0.subcons-final-pred.csv"%(
            outpath_this_seq, "final-prediction")
    (loc_def, loc_def_score) = GetLocDef(finalpredfile)
    date_str = time.strftime(FORMAT_DATETIME)
    info_finish = [ "seq_%d"%origIndex,
            str(seqLength), str(loc_def), str(loc_def_score),
            source_result, str(runtime),
            seqAnno.replace('\t', ' '), date_str]
    return info_finish
# }}}
def GetRefreshInterval(queuetime_in_sec, runtime_in_sec, method_submission):# {{{
    """Get refresh_interval for the webpage"""
    refresh_interval = 2.0
    t =  queuetime_in_sec + runtime_in_sec
    if t < 10:
        if method_submission == "web":
            refresh_interval = 2.0
        else:
            refresh_interval = 5.0
    elif t >= 10 and t < 40:
        refresh_interval = t / 2.0
    else:
        refresh_interval = 20.0
    return refresh_interval

# }}}
def WriteDateTimeTagFile(outfile, logfile, errfile):# {{{
    if not os.path.exists(outfile):
        date_str = time.strftime(FORMAT_DATETIME)
        try:
            myfunc.WriteFile(date_str, outfile)
            msg = "Write tag file %s succeeded"%(outfile)
            myfunc.WriteFile("[%s] %s\n"%(date_str, msg),  logfile, "a", True)
        except Exception as e:
            msg = "Failed to write to file %s with message: \"%s\""%(outfile, str(e))
            myfunc.WriteFile("[%s] %s\n"%(date_str, msg),  errfile, "a", True)
# }}}
def DeleteOldResult(path_result, path_log, logfile, MAX_KEEP_DAYS=180):#{{{
    """Delete jobdirs that are finished > MAX_KEEP_DAYS
    return True if therer is at least one result folder been deleted
    """
    finishedjoblogfile = "%s/finished_job.log"%(path_log)
    finished_job_dict = myfunc.ReadFinishedJobLog(finishedjoblogfile)
    isOldRstdirDeleted = False
    for jobid in finished_job_dict:
        li = finished_job_dict[jobid]
        try:
            finish_date_str = li[8]
        except IndexError:
            finish_date_str = ""
            pass
        if finish_date_str != "":
            isValidFinishDate = True
            try:
                finish_date = datetime_str_to_time(finish_date_str)
            except ValueError:
                isValidFinishDate = False

            if isValidFinishDate:
                current_time = datetime.now(timezone(TZ))
                timeDiff = current_time - finish_date
                if timeDiff.days > MAX_KEEP_DAYS:
                    rstdir = "%s/%s"%(path_result, jobid)
                    msg = "\tjobid = %s finished %d days ago (>%d days), delete."%(jobid, timeDiff.days, MAX_KEEP_DAYS)
                    loginfo(msg, logfile)
                    shutil.rmtree(rstdir)
                    isOldRstdirDeleted = True
    return isOldRstdirDeleted
#}}}
def CleanServerFile(logfile, errfile):#{{{
    """Clean old files on the server"""
# clean tmp files
    msg = "CleanServerFile..."
    date_str = time.strftime(FORMAT_DATETIME)
    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), logfile, "a", True)
    cmd = ["bash", "%s/clean_server_file.sh"%(rundir)]
    RunCmd(cmd, logfile, errfile)
#}}}
def SendEmail_on_finish(jobid, base_www_url, finish_status, name_server, from_email, to_email, contact_email, logfile="", errfile=""):# {{{
    """Send notification email to the user for the web-server, the name
    of the web-server is specified by the var 'name_server'
    """
    err_msg = ""
    if os.path.exists(errfile):
        err_msg = myfunc.ReadFile(errfile)

    subject = "Your result for %s JOBID=%s"%(name_server, jobid)
    if finish_status == "success":
        bodytext = """
Your result is ready at %s/pred/result/%s

Thanks for using %s

    """%(base_www_url, jobid, name_server)
    elif finish_status == "failed":
        bodytext="""
We are sorry that your job with jobid %s is failed.

Please contact %s if you have any questions.

Attached below is the error message:
%s
        """%(jobid, contact_email, err_msg)
    else:
        bodytext="""
Your result is ready at %s/pred/result/%s

We are sorry that %s failed to predict some sequences of your job.

Please re-submit the queries that have been failed.

If you have any further questions, please contact %s.

Attached below is the error message:
%s
        """%(base_www_url, jobid, name_server, contact_email, err_msg)

    date_str = time.strftime(FORMAT_DATETIME)
    msg =  "Sendmail %s -> %s, %s"%(from_email, to_email, subject)
    myfunc.WriteFile("[%s] %s\n"% (date_str, msg), logfile, "a", True)
    rtValue = myfunc.Sendmail(from_email, to_email, subject, bodytext)
    if rtValue != 0:
        msg =  "Sendmail to {} failed with status {}".format(to_email, rtValue)
        myfunc.WriteFile("[%s] %s\n"%(date_str, msg), errfile, "a", True)
        return 1
    else:
        return 0
# }}}
def CleanJobFolder_Subcons(rstdir):# {{{
    """Clean the jobfolder for Subcons after finishing"""
    flist =[
            "%s/remotequeue_seqindex.txt"%(rstdir),
            "%s/torun_seqindex.txt"%(rstdir)
            ]
    for f in flist:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass
# }}}
def loginfo(msg, outfile):# {{{
    """Write loginfo to outfile, appending current time"""
    date_str = time.strftime(FORMAT_DATETIME)
    myfunc.WriteFile("[%s] %s\n"%(date_str, msg), outfile, "a", True)
# }}}
def ArchiveLogFile(path_log, threshold_logfilesize=20*1024*1024):# {{{
    """Archive some of the log files if they are too big"""
    gen_logfile = "%s/qd_fe.log"%(path_log)
    gen_errfile = "%s/qd_fe.err"%(path_log)
    flist = [gen_logfile, gen_errfile,
            "%s/restart_qd_fe.cgi.log"%(path_log),
            "%s/debug.log"%(path_log),
            "%s/clean_cached_result.py.log"%(path_log)
            ]

    for f in flist:
        if os.path.exists(f):
            myfunc.ArchiveFile(f, threshold_logfilesize)
# }}}
