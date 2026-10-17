package com.voicestudio.mobile

import android.content.Context
import android.content.pm.ServiceInfo
import androidx.concurrent.futures.CallbackToFutureAdapter
import androidx.test.core.app.ApplicationProvider
import androidx.work.*
import androidx.work.testing.TestListenableWorkerBuilder
import com.voicestudio.mobile.data.*
import kotlinx.coroutines.*
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[34])
class WorkerAvailabilityRegressionTest {
    private suspend fun worker(foreground:ForegroundUpdater):Pair<DubWorker,MockWebServer> {
        val context=ApplicationProvider.getApplicationContext<Context>()
        val server=MockWebServer().apply {start()}
        val host=server.url("/").toString()
        SessionStore(context).update {Preferences(activeUrl=host)}
        server.enqueue(MockResponse().setBody("""{"active":"argos","engines":[{"id":"argos","category":"offline","installed":true,"ready":true}]}"""))
        server.enqueue(MockResponse().setBody("""{"job_id":"job","task_id":"prep"}"""))
        server.enqueue(MockResponse().setBody("""{"job":{"status":"done"},"events":[{"seq":1,"payload":"{\"percent\":0.5}"}]}"""))
        server.enqueue(MockResponse().setBody("""{"segments":[{"start":0,"end":1,"text":"Speech"}]}"""))
        return TestListenableWorkerBuilder<DubWorker>(context).setInputData(workDataOf(
            "host" to host,"job" to "job","link" to "https://example.test/video",
            "languages" to emptyArray<String>(),"names" to emptyArray<String>(),
            "translation_provider" to "argos","translation_category" to "offline"))
            .setForegroundUpdater(foreground).build() to server
    }
    @Test fun foregroundRefusalDoesNotFailUploadOrSubsequentProgress()=runBlocking {
        var attempts=0
        val (worker,server)=worker(ForegroundUpdater {_,_,_->
            attempts++
            CallbackToFutureAdapter.getFuture<Void> {it.setException(IllegalStateException("foreground start refused"));"refused"}
        })
        try {
            assertEquals(ListenableWorker.Result.success(workDataOf("job" to "job","stage" to "mobile.android.stage_done")),worker.doWork())
            assertTrue(attempts>=4)
            assertEquals(4,server.requestCount)
        } finally {server.shutdown()}
    }
    @Test fun foregroundInfoDeclaresDataSyncAndCancellationPropagates()=runBlocking {
        val (worker,server)=worker(ForegroundUpdater {_,_,_->
            CallbackToFutureAdapter.getFuture<Void> {it.setException(CancellationException("cancel"));"cancelled"}
        })
        try {
            assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,worker.getForegroundInfo().foregroundServiceType)
            val context=ApplicationProvider.getApplicationContext<Context>()
            val service=context.packageManager.getServiceInfo(android.content.ComponentName(context,
                "androidx.work.impl.foreground.SystemForegroundService"),0)
            assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,service.foregroundServiceType)
            try {worker.doWork();fail("Cancellation must propagate")} catch(expected:CancellationException) { }
            assertEquals(1,server.requestCount)
        } finally {server.shutdown()}
    }
}
