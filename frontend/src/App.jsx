import { useEffect, useState, useRef } from 'react';
import './App.css';
import { useProctoring, API } from './ai/useProctoring';
import { Preparation, StatusPanel, TeacherAIEvents } from './ai/Panels';

function App() {
  const [accessCode, setAccessCode] = useState('');
  const [consent, setConsent] = useState(false);
  const [cloudConsent, setCloudConsent] = useState(false);
  const [headOnly, setHeadOnly] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isAdminView, setIsAdminView] = useState(false);
  const [adminEvents, setAdminEvents] = useState([]);
  
  const [warnings, setWarnings] = useState([]);
  const [status, setStatus] = useState("Exam in Progress...");
  const [examEnded, setExamEnded] = useState(false);
  const [examSubmitted, setExamSubmitted] = useState(false);
  const [showPopup, setShowPopup] = useState(false);
  const [latestWarningMsg, setLatestWarningMsg] = useState("");
  
  const [timeLeft, setTimeLeft] = useState(600);
  const [questions, setQuestions] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState({});

  const videoRef = useRef(null);
  const examContainerRef = useRef(null);
  const ai = useProctoring(videoRef);
  const phoneWarnedRef = useRef(false);
  const stopCameraChecks = ai.stop;

  useEffect(() => {
    if (examEnded || examSubmitted) void stopCameraChecks();
  }, [examEnded, examSubmitted, stopCameraChecks]);

  const fetchAdminEvents = () => {
    fetch(`${API}/api/proctor/events`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setAdminEvents(data);
        }
      })
      .catch(err => console.error("Error fetching admin events:", err));
  };

  useEffect(() => {
    if (isAdminView) {
      fetchAdminEvents();
      const interval = setInterval(fetchAdminEvents, 5000);
      return () => clearInterval(interval);
    }
  }, [isAdminView]);

  // Function to capture and send webcam snapshot to backend
  const captureAndSendSnapshot = (currentStudentId) => {
    if (!videoRef.current) return;
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
      const imageData = canvas.toDataURL('image/jpeg', 0.7); // Base64 compressed image

      fetch(`${API}/api/proctor/save-snapshot`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          student_id: currentStudentId,
          image_data: imageData
        })
      }).catch(err => console.error("Snapshot upload error:", err));
    } catch (e) {
      console.error("Canvas snapshot error:", e);
    }
  };

  useEffect(() => {
    if (isLoggedIn && !examEnded && !examSubmitted) {
      // The pre-exam checks and legacy snapshots share the same browser stream.
      const initialSnapshot = setTimeout(() => captureAndSendSnapshot(studentId), 2000);

      if (examContainerRef.current && examContainerRef.current.requestFullscreen) {
        examContainerRef.current.requestFullscreen().catch(err => {
          console.log("Fullscreen request error:", err);
        });
      }

      fetch(`${API}/api/proctor/questions`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setQuestions(data);
          }
        })
        .catch(err => console.error("Error fetching questions:", err));

      // Periodic Snapshot Interval (Every 60 seconds)
      const snapshotInterval = setInterval(() => {
        captureAndSendSnapshot(studentId);
      }, 60000);

      return () => { clearInterval(snapshotInterval); clearTimeout(initialSnapshot); };
    }
  }, [isLoggedIn, studentId, examEnded, examSubmitted]);

  // AI Phone Detection Warning Logic
  useEffect(() => {
    if (!isLoggedIn || examEnded || examSubmitted) return;

    // AI state se phone ka count check karein
    const phoneCount = ai.state?.objects?.counts?.['cell phone'] || 0;

    if (ai.state?.frame_fresh && phoneCount > 0) {
      if (!phoneWarnedRef.current) {
        phoneWarnedRef.current = true; // Spam rokne ke liye flag ON karein

        const warningMsg = `Mobile phone detected at ${new Date().toLocaleTimeString()}`;

        // Live Warning Logs mein add karein aur 3 par terminate karein
        setWarnings(prev => {
          const newWarnings = [warningMsg, ...prev];
          if (newWarnings.length >= 3) {
            setExamEnded(true);
            setStatus("Exam Terminated & Disqualified!");
            setShowPopup(false);
          } else {
            setLatestWarningMsg(warningMsg);
            setShowPopup(true);
            setStatus("Suspicious Activity Detected!");
          }
          return newWarnings;
        });

        // Backend server par violation event bhejein
        fetch(`${API}/api/proctor/log-event`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            student_id: studentId || "Unknown_Student",
            event_type: "Phone-Detected",
            timestamp: new Date().toLocaleTimeString()
          })
        }).catch(err => console.error("Error logging AI event:", err));

        // 15 seconds baad flag reset karein taake dobara phone aane par nayi warning lag sake
        setTimeout(() => { 
          phoneWarnedRef.current = false; 
        }, 15000);
      }
    }
  }, [ai.state, isLoggedIn, examEnded, examSubmitted, studentId]);

  useEffect(() => {
    if (!isLoggedIn || examEnded || examSubmitted) return;

    const timer = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          setExamSubmitted(true);
          setStatus("Time's up! Exam Submitted Automatically");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isLoggedIn, examEnded, examSubmitted]);

  useEffect(() => {
    if (!isLoggedIn || examEnded || examSubmitted) return;

    const sendEventToBackend = async (eventType) => {
      try {
        await fetch(`${API}/api/proctor/log-event`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            student_id: studentId || "Unknown_Student",
            event_type: eventType,
            timestamp: new Date().toLocaleTimeString()
          })
        });
      } catch (err) {
        console.error("Error logging event:", err);
      }
    };

    const triggerWarning = (msg, eventType) => {
      if (examSubmitted || examEnded) return;
      
      setWarnings(prev => {
        const newWarnings = [msg, ...prev];
        if (newWarnings.length >= 3) {
          setExamEnded(true);
          setStatus("Exam Terminated & Disqualified!");
          setShowPopup(false);
        } else {
          setLatestWarningMsg(msg);
          setShowPopup(true);
          setStatus("Suspicious Activity Detected!");
        }
        return newWarnings;
      });

      sendEventToBackend(eventType);
    };

    const handleVisibilityChange = () => {
      if (document.hidden && !examEnded && !examSubmitted) {
        triggerWarning(`Tab switched or minimized at ${new Date().toLocaleTimeString()}`, "Tab-Switch");
      }
    };

    const handleBlur = () => {
      if (!examEnded && !examSubmitted) {
        triggerWarning(`Window focus lost at ${new Date().toLocaleTimeString()}`, "Focus-Lost");
      }
    };

    const handleFullscreenChange = () => {
      if (!document.fullscreenElement && !examEnded && !examSubmitted) {
        triggerWarning(`Exited Fullscreen mode at ${new Date().toLocaleTimeString()}`, "Fullscreen-Exit");
      }
    };

    const handleCopy = (e) => {
      e.preventDefault();
      triggerWarning(`Tried to copy text at ${new Date().toLocaleTimeString()}`, "Copy-Attempt");
    };

    const handlePaste = (e) => {
      e.preventDefault();
      triggerWarning(`Tried to paste text at ${new Date().toLocaleTimeString()}`, "Paste-Attempt");
    };

    const handleContextMenu = (e) => {
      e.preventDefault();
      triggerWarning(`Tried to use Right-Click at ${new Date().toLocaleTimeString()}`, "Right-Click");
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("blur", handleBlur);
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("copy", handleCopy);
    document.addEventListener("paste", handlePaste);
    document.addEventListener("contextmenu", handleContextMenu);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("blur", handleBlur);
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("copy", handleCopy);
      document.removeEventListener("paste", handlePaste);
      document.removeEventListener("contextmenu", handleContextMenu);
    };
  }, [isLoggedIn, examEnded, examSubmitted, studentId]);

  const handleStartExam = async (e) => {
    e.preventDefault();
    if (!studentId.trim()) {
      alert("Kripya apni Student ID ya Roll Number enter karein!");
      return;
    }
    if (!consent || !ai.capabilities) return;
    const started = await ai.start({ studentId: studentId.trim(), accessCode, consent, cloudConsent, headOnly });
    if (!started) return;
    setAccessCode('');
    if (ai.capabilities.enabled) setPreparing(true);
    else setIsLoggedIn(true);
  };

  const handleAnswerChange = (e) => {
    const qId = questions[currentIndex].id;
    setAnswers({ ...answers, [qId]: e.target.value });
  };

  const handleSubmitExam = () => {
    setExamSubmitted(true);
    setStatus("Exam Submitted Successfully");
    if (document.exitFullscreen && document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
  };

  const formatTime = (seconds) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs < 10 ? '0' : ''}${secs}`;
  };

  if (isAdminView) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f4f7f6', padding: '30px', fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif" }}>
        <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '25px', backgroundColor: '#fff', padding: '20px 30px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
            <div>
              <h2 style={{ margin: 0, color: '#2c3e50' }}>👨‍🏫 Teacher Proctoring Dashboard</h2>
              <p style={{ margin: '5px 0 0 0', color: '#7f8c8d', fontSize: '14px' }}>Real-time student violation monitoring logs</p>
            </div>
            <button 
              onClick={() => setIsAdminView(false)}
              style={{ backgroundColor: '#e74c3c', color: 'white', border: 'none', padding: '10px 20px', borderRadius: '6px', cursor: 'pointer', fontWeight: '600' }}>
              Back to Login / Student View
            </button>
          </div>

          <div style={{ backgroundColor: '#fff', padding: '25px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
            <TeacherAIEvents />
            <h3 style={{ marginTop: 0, color: '#34495e', borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>Violation Logs ({adminEvents.length})</h3>
            {adminEvents.length === 0 ? (
              <p style={{ color: '#95a5a6', fontStyle: 'italic', textAlign: 'center', padding: '20px' }}>No violation logs recorded in database yet.</p>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', marginTop: '15px' }}>
                <thead>
                  <tr style={{ backgroundColor: '#f8f9fa', borderBottom: '2px solid #bdc3c7', color: '#2c3e50' }}>
                    <th style={{ padding: '12px' }}>ID</th>
                    <th style={{ padding: '12px' }}>Student Roll No</th>
                    <th style={{ padding: '12px' }}>Violation Event</th>
                    <th style={{ padding: '12px' }}>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {adminEvents.map((ev) => (
                    <tr key={ev.id} style={{ borderBottom: '1px solid #ecf0f1' }}>
                      <td style={{ padding: '12px', color: '#7f8c8d' }}>{ev.id}</td>
                      <td style={{ padding: '12px', fontWeight: '600', color: '#2980b9' }}>{ev.student_id}</td>
                      <td style={{ padding: '12px', color: '#c0392b', fontWeight: '600' }}>{ev.event_type}</td>
                      <td style={{ padding: '12px', color: '#555' }}>{ev.timestamp}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (preparing) {
    return <Preparation ai={ai} headOnly={headOnly} setHeadOnly={setHeadOnly}
      onCancel={async () => { await ai.stop(); setPreparing(false); }}
      onBegin={async () => {
        // Request fullscreen within the user gesture, before the network round trip.
        document.documentElement.requestFullscreen?.().catch(() => {});
        if (await ai.command('begin')) { setPreparing(false); setIsLoggedIn(true); }
      }} />;
  }

  if (!isLoggedIn) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#f4f7f6',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
      }}>
        <div style={{
          backgroundColor: '#ffffff',
          padding: '40px',
          borderRadius: '12px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
          maxWidth: '400px',
          width: '90%',
          textAlign: 'center'
        }}>
          <h2 style={{ color: '#2c3e50', marginBottom: '10px' }}>🛡️ TrustMatrix Exam Portal</h2>
          <p style={{ color: '#7f8c8d', fontSize: '14px', marginBottom: '25px' }}>
            Exam shuru karne se pehle apni unique Student ID ya Roll Number darj karein.
          </p>
          <form onSubmit={handleStartExam}>
            <input 
              type="text"
              placeholder="e.g. BCS-21F-045"
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              style={{
                width: '100%',
                padding: '12px 15px',
                borderRadius: '6px',
                border: '1px solid #bdc3c7',
                marginBottom: '20px',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
            {ai.capabilities?.enabled && <label className="ai-login-field">Exam access code
              <input type="password" autoComplete="off" value={accessCode} onChange={e => setAccessCode(e.target.value)} required />
            </label>}
            <label className="ai-login-field"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} required />
              I agree to webcam processing and the existing initial and 60-second stored snapshots. AI analysis frames are processed by the exam server without being saved.
            </label>
            {ai.capabilities?.enabled && <label className="ai-login-field"><input type="checkbox" checked={cloudConsent}
              disabled={!ai.capabilities.cloud_configured} onChange={e => setCloudConsent(e.target.checked)} />
              I also agree to sampled frames being sent to Roboflow for phone, book and person detection.
              {!ai.capabilities.cloud_configured && ' Object checks require operator configuration.'}
            </label>}
            {ai.error && <p role="alert" className="ai-error">{ai.error}</p>}
            {ai.busy && <p role="status">Preparing camera and models…</p>}
            <button
              disabled={ai.busy || !ai.capabilities || !consent}
              type="submit"
              style={{
                width: '100%',
                backgroundColor: '#3498db',
                color: 'white',
                border: 'none',
                padding: '12px',
                borderRadius: '6px',
                fontWeight: '600',
                fontSize: '15px',
                cursor: 'pointer',
                marginBottom: '15px'
              }}>
              {ai.capabilities?.enabled ? 'Check camera before exam' : 'Start Secure Exam'}
            </button>
          </form>

          <div style={{ borderTop: '1px solid #ecf0f1', paddingTop: '15px', marginTop: '10px' }}>
            <button 
              onClick={() => setIsAdminView(true)}
              style={{
                backgroundColor: '#2c3e50',
                color: 'white',
                border: 'none',
                padding: '10px 15px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: '600',
                width: '100%'
              }}>
              👨‍🏫 Open Teacher / Admin Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (examEnded) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#f4f7f6',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
      }}>
        <div style={{
          backgroundColor: '#ffffff',
          padding: '40px',
          borderRadius: '12px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
          maxWidth: '450px',
          width: '90%',
          textAlign: 'center',
          borderTop: '5px solid #c0392b'
        }}>
          <div style={{ fontSize: '50px', marginBottom: '15px' }}>❌</div>
          <h2 style={{ color: '#c0392b', marginBottom: '10px' }}>Exam Terminated & Disqualified!</h2>
          <p style={{ color: '#7f8c8d', fontSize: '14px', marginBottom: '20px' }}>
            Student: <strong style={{ color: '#2c3e50' }}>{studentId}</strong>. Aapne max allowed warnings cross kar li hain.
          </p>
          <button 
            onClick={() => window.location.reload()}
            style={{
              backgroundColor: '#c0392b',
              color: 'white',
              border: 'none',
              padding: '12px 25px',
              borderRadius: '6px',
              fontWeight: '600',
              cursor: 'pointer'
            }}>
            Exit / Return Home
          </button>
        </div>
      </div>
    );
  }

  if (examSubmitted) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#f4f7f6',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
      }}>
        <div style={{
          backgroundColor: '#ffffff',
          padding: '40px',
          borderRadius: '12px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
          maxWidth: '450px',
          width: '90%',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '50px', marginBottom: '15px' }}>🎉</div>
          <h2 style={{ color: '#27ae60', marginBottom: '10px' }}>Exam Submitted Successfully!</h2>
          <p style={{ color: '#7f8c8d', fontSize: '14px', marginBottom: '20px' }}>
            Thank you, <strong style={{ color: '#2c3e50' }}>{studentId}</strong>. Your exam and snapshots have been recorded.
          </p>
          <button 
            onClick={() => window.location.reload()}
            style={{
              backgroundColor: '#3498db',
              color: 'white',
              border: 'none',
              padding: '12px 25px',
              borderRadius: '6px',
              fontWeight: '600',
              cursor: 'pointer'
            }}>
            Exit / Back to Home
          </button>
        </div>
      </div>
    );
  }

  const currentQuestion = questions[currentIndex];

  return (
    <div ref={examContainerRef} style={{ 
      minHeight: '100vh', 
      backgroundColor: '#f4f7f6', 
      fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
      padding: '30px',
      boxSizing: 'border-box'
    }}>
      <header style={{ 
        backgroundColor: '#ffffff', 
        padding: '20px 30px', 
        borderRadius: '12px', 
        boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '25px'
      }}>
        <div>
          <h1 style={{ margin: 0, color: '#2c3e50', fontSize: '24px' }}>🛡️ TrustMatrix AI Proctoring</h1>
          <p style={{ margin: '5px 0 0 0', color: '#7f8c8d', fontSize: '14px' }}>
            Student: <strong style={{ color: '#2980b9' }}>{studentId}</strong> (Periodic Snapshots Active)
          </p>
        </div>

        <div style={{
          backgroundColor: '#f39c12',
          color: 'white',
          padding: '8px 16px',
          borderRadius: '20px',
          fontWeight: 'bold',
          fontSize: '15px'
        }}>
          ⏱️ Time Left: {formatTime(timeLeft)}
        </div>

        <div style={{ 
          padding: '8px 16px', 
          borderRadius: '20px', 
          backgroundColor: '#d4efdf',
          color: '#196f3d',
          fontWeight: '600',
          fontSize: '14px'
        }}>
          {status}
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '25px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ 
            backgroundColor: '#ffffff', 
            padding: '25px', 
            borderRadius: '12px', 
            boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
            borderLeft: '5px solid #3498db'
          }}>
            {questions.length > 0 ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <span style={{ 
                    backgroundColor: '#ebf5fb', 
                    color: '#2980b9', 
                    padding: '4px 10px', 
                    borderRadius: '4px', 
                    fontSize: '12px', 
                    fontWeight: 'bold' 
                  }}>
                    QUESTION {currentIndex + 1} OF {questions.length}
                  </span>
                </div>
                <h3 style={{ color: '#2c3e50', marginTop: '10px', marginBottom: '15px' }}>
                  {currentQuestion.question_text}
                </h3>

                <div style={{ marginTop: '15px' }}>
                  <label style={{ display: 'block', fontWeight: '600', color: '#34495e', marginBottom: '8px', fontSize: '14px' }}>
                    Your Answer:
                  </label>
                  <textarea 
                    rows="6"
                    placeholder="Type your answer here..."
                    value={answers[currentQuestion.id] || ""}
                    onChange={handleAnswerChange}
                    style={{
                      width: '100%',
                      padding: '12px',
                      borderRadius: '8px',
                      border: '1px solid #bdc3c7',
                      fontSize: '14px',
                      fontFamily: 'inherit',
                      boxSizing: 'border-box',
                      resize: 'vertical',
                      backgroundColor: '#ffffff'
                    }}
                  />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
                  <button 
                    onClick={() => setCurrentIndex(prev => Math.max(prev - 1, 0))}
                    disabled={currentIndex === 0}
                    style={{
                      padding: '10px 20px',
                      backgroundColor: currentIndex === 0 ? '#bdc3c7' : '#95a5a6',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: currentIndex === 0 ? 'not-allowed' : 'pointer',
                      fontWeight: '600'
                    }}>
                    Previous
                  </button>

                  {currentIndex < questions.length - 1 ? (
                    <button 
                      onClick={() => setCurrentIndex(prev => Math.min(prev + 1, questions.length - 1))}
                      style={{
                        padding: '10px 20px',
                        backgroundColor: '#3498db',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontWeight: '600'
                      }}>
                      Next Question
                    </button>
                  ) : (
                    <button 
                      onClick={handleSubmitExam}
                      style={{
                        padding: '10px 20px',
                        backgroundColor: '#2ecc71',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontWeight: '600'
                      }}>
                      Submit Exam
                    </button>
                  )}
                </div>
              </>
            ) : (
              <p style={{ color: '#7f8c8d', textAlign: 'center', padding: '20px' }}>Loading questions from database...</p>
            )}
          </div>

          <div style={{ 
            backgroundColor: '#ffffff', 
            padding: '25px', 
            borderRadius: '12px', 
            boxShadow: '0 4px 12px rgba(0,0,0,0.05)' 
          }}>
            <h3 style={{ color: '#2c3e50', marginTop: 0, borderBottom: '2px solid #ecf0f1', paddingBottom: '10px' }}>
              Live Warning Logs ({warnings.length}/3)
            </h3>
            {warnings.length === 0 ? (
              <p style={{ color: '#95a5a6', fontStyle: 'italic' }}>No violations detected yet. Keep up the good work!</p>
            ) : (
              <ul style={{ paddingLeft: '20px', margin: 0 }}>
                {warnings.map((warn, index) => (
                  <li key={index} style={{ color: '#c0392b', marginBottom: '8px', fontWeight: '500' }}>
                    {warn}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div style={{ 
          backgroundColor: '#ffffff', 
          padding: '20px', 
          borderRadius: '12px', 
          boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
          height: 'fit-content',
          textAlign: 'center'
        }}>
          <h3 style={{ color: '#2c3e50', marginTop: 0, marginBottom: '15px' }}>Proctoring Camera</h3>
          {ai.capabilities?.enabled && <>
            <StatusPanel ai={ai} compact />
            <button className="ai-retry" onClick={() => ai.command('retry')}>Retry camera checks / recalibrate</button>
          </>}
          <div style={{ 
            borderRadius: '8px', 
            overflow: 'hidden', 
            backgroundColor: '#000',
            boxShadow: 'inset 0 0 10px rgba(0,0,0,0.5)'
          }}>
            <video 
              ref={node => ai.attachVideo(node)}
              autoPlay 
              playsInline 
              muted 
              style={{ width: '100%', height: '220px', objectFit: 'cover', display: 'block' }} 
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginTop: '12px' }}>
            <span style={{ height: '10px', width: '10px', backgroundColor: '#2ecc71', borderRadius: '50%', display: 'inline-block' }}></span>
            <span style={{ fontSize: '13px', color: '#27ae60', fontWeight: '600' }}>{ai.capabilities?.enabled ? (ai.state?.frame_fresh ? 'AI camera checks active' : 'AI camera checks unavailable') : 'Camera active'}</span>
          </div>
        </div>
      </div>

      {showPopup && !examEnded && !examSubmitted && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          backgroundColor: 'rgba(0, 0, 0, 0.6)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1000,
          backdropFilter: 'blur(3px)'
        }}>
          <div style={{
            backgroundColor: '#ffffff',
            padding: '30px',
            borderRadius: '12px',
            textAlign: 'center',
            boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
            maxWidth: '420px',
            width: '90%'
          }}>
            <div style={{ fontSize: '40px', marginBottom: '10px' }}>⚠️</div>
            <h2 style={{ color: '#d35400', marginTop: 0 }}>Cheating Attempt Detected!</h2>
            <p style={{ fontWeight: '600', color: '#2c3e50', margin: '15px 0' }}>{latestWarningMsg}</p>
            <p style={{ fontSize: '13px', color: '#7f8c8d', lineHeight: '1.5', marginBottom: '20px' }}>
              Warning {warnings.length}/3. 3rd warning par exam automatically terminate kar diya jayega!
            </p>
            <button 
              onClick={() => {
                setShowPopup(false);
                if (examContainerRef.current && examContainerRef.current.requestFullscreen) {
                  examContainerRef.current.requestFullscreen().catch(() => {});
                }
              }}
              style={{
                backgroundColor: '#3498db',
                color: 'white',
                border: 'none',
                padding: '12px 25px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: '600',
                fontSize: '14px'
              }}>
              I Understand / Resume Exam
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
