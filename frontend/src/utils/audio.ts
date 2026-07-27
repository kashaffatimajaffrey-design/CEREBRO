// CEREBRO - Synthesizer Engine (Real-time Web Audio API)

let isAudioMuted = false;

// Check if audio is enabled in browser
export const toggleMute = () => {
  isAudioMuted = !isAudioMuted;
  // Play short confirmation beep when unmuting
  if (!isAudioMuted) {
    playCyberSFX('hover');
  }
  return isAudioMuted;
};

export const getMuteStatus = () => {
  return isAudioMuted;
};

export const playCyberSFX = (type: 'hover' | 'click' | 'scan' | 'success' | 'alarm' | 'omnitrix') => {
  if (isAudioMuted) return;

  try {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;

    const ctx = new AudioContextClass();
    
    // Resume audio context if suspended (browser security autoplay policies)
    if (ctx.state === 'suspended') {
      ctx.resume();
    }

    const playTone = (freq: number, duration: number, typeOsc: OscillatorType = 'sine', gainVal = 0.025) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      
      osc.type = typeOsc;
      osc.frequency.setValueAtTime(freq, ctx.currentTime);
      
      gain.gain.setValueAtTime(gainVal, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
      
      osc.connect(gain);
      gain.connect(ctx.destination);
      
      osc.start();
      osc.stop(ctx.currentTime + duration);
    };

    switch (type) {
      case 'hover': {
        // High-pitch micro click
        playTone(1800, 0.04, 'sine', 0.015);
        break;
      }
      case 'click': {
        // Double fast agent blip
        playTone(950, 0.08, 'sine', 0.02);
        setTimeout(() => {
          playTone(1420, 0.12, 'sine', 0.015);
        }, 40);
        break;
      }
      case 'scan': {
        // Futuristic frequency scan sweep
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(350, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(2200, ctx.currentTime + 0.65);
        
        gain.gain.setValueAtTime(0.025, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.65);
        
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.65);
        break;
      }
      case 'success': {
        // Ascending pentatonic chord confirmation
        const notes = [523.25, 659.25, 783.99, 987.77, 1318.51]; // C5, E5, G5, B5, E6
        notes.forEach((freq, index) => {
          setTimeout(() => {
            playTone(freq, 0.4, 'sine', 0.015);
          }, index * 60);
        });
        break;
      }
      case 'alarm': {
        // Alternating high threat siren warble
        const duration = 0.8;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sawtooth';
        
        // Warble frequency modulator
        osc.frequency.setValueAtTime(440, ctx.currentTime);
        for (let t = 0; t < duration; t += 0.1) {
          osc.frequency.setValueAtTime(t % 0.2 < 0.1 ? 680 : 340, ctx.currentTime + t);
        }
        
        gain.gain.setValueAtTime(0.02, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
        
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + duration);
        break;
      }
      case 'omnitrix': {
        // Deep resonant Omnitrix activation energy pulse
        const duration = 1.2;
        const osc = ctx.createOscillator();
        const subOsc = ctx.createOscillator();
        const filter = ctx.createBiquadFilter();
        const gain = ctx.createGain();
        
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(90, ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(140, ctx.currentTime + duration);

        subOsc.type = 'sine';
        subOsc.frequency.setValueAtTime(45, ctx.currentTime);
        
        filter.type = 'lowpass';
        filter.frequency.setValueAtTime(180, ctx.currentTime);
        filter.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.4);
        filter.frequency.exponentialRampToValueAtTime(100, ctx.currentTime + duration);
        filter.Q.setValueAtTime(8, ctx.currentTime);

        gain.gain.setValueAtTime(0.06, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0.08, ctx.currentTime + 0.3);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
        
        osc.connect(filter);
        subOsc.connect(filter);
        filter.connect(gain);
        gain.connect(ctx.destination);
        
        osc.start();
        subOsc.start();
        
        osc.stop(ctx.currentTime + duration);
        subOsc.stop(ctx.currentTime + duration);
        break;
      }
    }
  } catch (err) {
    console.warn('Real-time audio synthesis bypassed by host context', err);
  }
};
