package com.voicestudio.mobile

import android.app.Application
import android.content.Context
import android.content.pm.ServiceInfo
import androidx.concurrent.futures.CallbackToFutureAdapter
import androidx.test.core.app.ApplicationProvider
import androidx.work.*
import androidx.work.testing.TestListenableWorkerBuilder
import com.voicestudio.mobile.data.PhoneDubWorker
import kotlinx.coroutines.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[34])
class PhoneDubWorkerTest {
    private val context get()=ApplicationProvider.getApplicationContext<Context>()
    @Test fun foregroundIsRequiredAndCancellationPropagatesWithoutNetwork()=runBlocking {
        var promoted=false
        val worker=TestListenableWorkerBuilder<PhoneDubWorker>(context).setInputData(workDataOf("job" to java.util.UUID.randomUUID().toString()))
            .setForegroundUpdater {_,_,info ->
                promoted=true;assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,info.foregroundServiceType)
                CallbackToFutureAdapter.getFuture<Void> {it.setException(CancellationException("stop"));"cancelled"}
            }.build()
        (context as Application).let {org.robolectric.Shadows.shadowOf(it).denyPermissions(android.Manifest.permission.POST_NOTIFICATIONS)}
        try {worker.doWork();fail()} catch(_:CancellationException) {}
        assertTrue(promoted)
        assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,worker.getForegroundInfo().foregroundServiceType)
    }
    @Test fun invalidCheckpointIsActionableWithoutComputerCredentials()=runBlocking {
        val worker=TestListenableWorkerBuilder<PhoneDubWorker>(context).setInputData(workDataOf("job" to java.util.UUID.randomUUID().toString()))
            .setForegroundUpdater {_,_,_->CallbackToFutureAdapter.getFuture<Void> {it.set(null);"foreground"}}.build()
        val result=worker.doWork()
        assertEquals(ListenableWorker.Result.failure(workDataOf("job" to worker.inputData.getString("job"),"error" to "mobile.simple.checkpoint_failed")),result)
    }
}
