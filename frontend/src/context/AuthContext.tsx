import React, { createContext, useContext, useState, useEffect } from 'react';
import { User, HistoryItem } from '../types';
import { 
  onAuthStateChanged, 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword, 
  signOut, 
  signInWithPopup, 
  GoogleAuthProvider 
} from 'firebase/auth';
import { 
  doc, 
  getDoc, 
  setDoc, 
  collection, 
  onSnapshot, 
  query, 
  orderBy,
  updateDoc,
  serverTimestamp,
  getDocFromServer
} from 'firebase/firestore';
import { auth, db, handleFirestoreError, OperationType } from '../services/firebase';

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
  addToHistory: (item: HistoryItem) => Promise<void>;
  updateUser: (data: { name: string, email: string }) => Promise<void>;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function getFriendlyAuthErrorMessage(err: any): string {
  const code = err?.code || '';
  const message = err?.message || String(err);
  
  if (code === 'auth/operation-not-allowed' || message.includes('operation-not-allowed')) {
    return "FIREBASE CONFIGURATION ERROR: The Email/Password sign-in provider is not enabled in your Firebase Console. Please open your Firebase Console (console.firebase.google.com), navigate to Authentication -> Sign-in method, click 'Add new provider', select 'Email/Password', enable it, and save the changes.";
  }
  if (code === 'auth/popup-closed-by-user' || message.includes('popup-closed-by-user')) {
    return "GOOGLE SIGN-IN BLOCKED/CLOSED: The Google SSO popup was closed or blocked. Because this preview runs in a sandboxed iframe, your browser may block third-party authentication cookies/popups. To fix this, click 'Open in New Tab' at the top right of the preview pane to run in a standalone window, or use Email/Password below.";
  }
  if (code === 'auth/cancelled-popup-request' || message.includes('cancelled-popup-request')) {
    return "GOOGLE SIGN-IN PENDING: Another login request is already in progress. Please wait a moment, reload the page, or click 'Open in New Tab' at the top right of the preview pane to run standalone.";
  }
  if (code === 'auth/network-request-failed' || message.includes('network-request-failed')) {
    return "NETWORK BLOCKED: Network connection failed. This is likely due to iframe sandbox restrictions in your browser. Please click 'Open in New Tab' at the top right of the preview pane to run standalone.";
  }
  if (message.includes('Pending promise') || message.includes('INTERNAL ASSERTION FAILED')) {
    return "SSO CONFLICT: A pending authentication request is stuck. Please click 'Open in New Tab' at the top right of the preview pane to sign in securely, or reload the page and sign in using Email/Password.";
  }
  if (code === 'auth/invalid-credential' || code === 'auth/wrong-password' || code === 'auth/user-not-found') {
    return "AUTHENTICATION FAILED: Invalid credentials. Please verify your email and key signature, or register a new footprint.";
  }
  return message || 'Secure Identity Exchange handshake disrupted.';
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Helper: test connection to Firestore of the remote database on startup
  useEffect(() => {
    async function validateConnection() {
      try {
        await getDocFromServer(doc(db, 'test', 'handshake'));
      } catch (error) {
        if (error instanceof Error && error.message.includes('the client is offline')) {
          console.error("Please check your Firebase configuration or network status.");
        }
      }
    }
    validateConnection();
  }, []);

  // Tracks Firebase Authentication State Loop
  useEffect(() => {
    const unsubscribeAuth = onAuthStateChanged(auth, async (firebaseUser) => {
      if (firebaseUser) {
        setLoading(true);
        const userRef = doc(db, 'users', firebaseUser.uid);
        
        try {
          // Retrieve/Verify security analyst profile
          let userSnap = await getDoc(userRef);
          
          if (!userSnap.exists()) {
            // Profile does not exist yet (e.g. from dynamic Google Single Sign-On)
            const newUserProfile = {
              id: firebaseUser.uid,
              name: firebaseUser.displayName || 'Cryptographic Analyst',
              email: firebaseUser.email || '',
              createdAt: serverTimestamp()
            };
            await setDoc(userRef, newUserProfile);
            userSnap = await getDoc(userRef);
          }

          const userData = userSnap.data();
          
          // Setup real-time real subcollection subscription listener for History logs
          const historyRef = collection(db, 'users', firebaseUser.uid, 'history');
          const historyQuery = query(historyRef, orderBy('date', 'desc'));

          const unsubscribeHistory = onSnapshot(historyQuery, (snapshot) => {
            const mappedHistoryList: HistoryItem[] = [];
            snapshot.forEach((histDoc) => {
              const histData = histDoc.data();
              
              // Map Timestamp to visual ISO string
              let dateString = new Date().toISOString();
              if (histData.date && typeof histData.date.toDate === 'function') {
                dateString = histData.date.toDate().toISOString();
              } else if (histData.date) {
                dateString = new Date(histData.date).toISOString();
              }

              mappedHistoryList.push({
                id: histDoc.id,
                date: dateString,
                type: histData.type,
                summary: histData.summary,
                result: histData.result
              });
            });

            setUser({
              id: firebaseUser.uid,
              name: userData?.name || 'Cryptographic Analyst',
              email: userData?.email || firebaseUser.email || '',
              history: mappedHistoryList
            });
            setLoading(false);
          }, (error) => {
            // Handle snapshot list operations errors conformant with rules
            handleFirestoreError(error, OperationType.LIST, `users/${firebaseUser.uid}/history`);
            setLoading(false);
          });

          return () => {
            unsubscribeHistory();
          };

        } catch (err) {
          console.error("Failed to compile user profile details: ", err);
          setLoading(false);
        }
      } else {
        setUser(null);
        setLoading(false);
      }
    });

    return () => unsubscribeAuth();
  }, []);

  const login = async (email: string, password: string) => {
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (err: any) {
      console.error("Firebase Login Incident: ", err);
      throw new Error(getFriendlyAuthErrorMessage(err));
    }
  };

  const signup = async (name: string, email: string, password: string) => {
    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const firebaseUser = userCredential.user;
      
      // Save full static profile shape inside the users database conformant with security filters
      const userRef = doc(db, 'users', firebaseUser.uid);
      await setDoc(userRef, {
        id: firebaseUser.uid,
        name: name,
        email: email,
        createdAt: serverTimestamp()
      });
    } catch (err: any) {
      console.error("Firebase Signup Incident: ", err);
      throw new Error(getFriendlyAuthErrorMessage(err));
    }
  };

  const loginWithGoogle = async () => {
    const provider = new GoogleAuthProvider();
    try {
      await signInWithPopup(auth, provider);
    } catch (err: any) {
      console.error("Google SSO Incident: ", err);
      throw new Error(getFriendlyAuthErrorMessage(err));
    }
  };

  const logout = async () => {
    await signOut(auth);
  };

  const addToHistory = async (item: HistoryItem) => {
    if (!user) {
      throw new Error('Analyst must be safely connected to transmit threat records.');
    }
    const path = `users/${user.id}/history/${item.id}`;
    try {
      const recordDocRef = doc(db, 'users', user.id, 'history', item.id);
      await setDoc(recordDocRef, {
        id: item.id,
        date: serverTimestamp(), // Conformant to rules strict request.time validation
        type: item.type,
        summary: item.summary,
        result: item.result
      });
    } catch (err) {
      handleFirestoreError(err, OperationType.CREATE, path);
    }
  };

  const updateUser = async (data: { name: string, email: string }) => {
    if (!user) {
      throw new Error('Analyst context is sterile.');
    }
    const path = `users/${user.id}`;
    try {
      const userRef = doc(db, 'users', user.id);
      await updateDoc(userRef, {
        name: data.name
        // Immutable field email is locked in rules, so only update name online
      });
    } catch (err) {
      handleFirestoreError(err, OperationType.UPDATE, path);
    }
  };

  return (
    <AuthContext.Provider value={{ user, login, signup, loginWithGoogle, logout, addToHistory, updateUser, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
