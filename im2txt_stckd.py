from keras.models import Model
from keras.layers import Input, LSTM, Dense, Embedding, Masking, GRU
from keras.optimizers import *
from keras.callbacks import ModelCheckpoint, CSVLogger
import numpy as np
import h5py
import json
import time
import datetime

def generate_input(train_file, vocab_json, batch_size, samples_per_story=5, is_captioning=False):
    image_embeddings = train_file["image_embeddings"]
    story_sentences = train_file["story_sentences"]
    num_samples = len(image_embeddings)
    idx_to_words = vocab_json["idx_to_words"]
    encoder_batch_input_data = np.zeros((batch_size * samples_per_story, 5, 4096))
    decoder_batch_input_data = np.zeros((batch_size * samples_per_story, 22),
                                        dtype=np.int32)
    decoder_batch_target_data = np.zeros(
        (batch_size * samples_per_story, story_sentences.shape[2], len(idx_to_words)),
        dtype=np.int32)

    while 1:

        for i in range(num_samples):

            if not(is_captioning):
                for j in range(samples_per_story):

                    encoder_row_start_range = ((i % batch_size) * samples_per_story) + j
                    encoder_row_end_range = ((i % batch_size) * samples_per_story) + 5
                    encoder_batch_input_data[encoder_row_start_range: encoder_row_end_range, j] = image_embeddings[i][j]

                    decoder_row = (i % batch_size) * samples_per_story + j

                    temp_story = story_sentences[i][j].tolist()
                    end_index = temp_story.index(2)
                    temp_story[end_index] = 0
                    decoder_batch_input_data[decoder_row] = np.array(temp_story)

            else:
                for j in range(samples_per_story):
                    encoder_batch_input_data[((i % batch_size) * samples_per_story) + j, 0] = image_embeddings[i][j]
                    decoder_batch_input_data[(i % batch_size) * samples_per_story + j] = story_sentences[i][j]

            story = story_sentences[i]
            for sentence_index in range(len(story)):
                sentence = story[sentence_index]
                for word_index in range(len(sentence)):
                    if word_index > 0:
                        decoder_batch_target_data[
                            ((i % batch_size) * samples_per_story) + sentence_index, word_index - 1, sentence[
                                word_index]] = 1

            if ((i + 1) % batch_size) == 0 and i != 0:

                print("yield i: ", i)
                yield ([encoder_batch_input_data, decoder_batch_input_data], decoder_batch_target_data)

                encoder_batch_input_data = np.zeros((batch_size * samples_per_story, 5, 4096))
                decoder_batch_input_data = np.zeros((batch_size * samples_per_story, 22), dtype= np.int32)
                decoder_batch_target_data = np.zeros(
                  (batch_size * samples_per_story, story_sentences.shape[2], len(vocab_json['idx_to_words'])),
                  dtype=np.int32)



vocab_json = json.load(open('./dataset/vist2017_vocabulary.json'))
train_file = h5py.File('./dataset/image_embeddings_to_sentence/stories_to_index_train.hdf5','r')
valid_file = h5py.File('./dataset/image_embeddings_to_sentence/stories_to_index_valid.hdf5','r')

batch_size = 13  # Batch size for training.
epochs = 20  # Number of epochs to train for.
latent_dim = 512  # Latent dimensionality of the encoding space.
word_embedding_size = 300 # Size of the word embedding space.
num_of_stacked_rnn = 3 # Number of Stacked RNN layers


learning_rate = 0.001
gradient_clip_value = 5.0

num_samples = len(train_file["story_ids"])
num_decoder_tokens = len(vocab_json['idx_to_words'])
valid_steps = len(valid_file["story_ids"])/batch_size

ts = time.time()
start_time = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H:%M:%S')

encoder_inputs = Input(shape=(None, 4096), name="encoder_input_layer")
mask_layer = Masking(mask_value=0, name="mask_layer")
mask_tensor = mask_layer(encoder_inputs)

encoder_lstm_name="encoder_lstm_"
encoder_0 = LSTM(latent_dim, return_sequences=True, return_state=True, name=encoder_lstm_name+"0")
encoder_outputs, _, _ = encoder_0(mask_tensor)
encoder_1 = LSTM(latent_dim, return_sequences=True, return_state=True, name=encoder_lstm_name+"1")
encoder_outputs_1, _, _ = encoder_1(encoder_outputs)
encoder_2 = LSTM(latent_dim, return_sequences=True, return_state=True, name=encoder_lstm_name+"2")
encoder_outputs_2, state_h, state_c = encoder_2(encoder_outputs_1)

encoder_states = [state_h, state_c]

decoder_inputs = Input(shape=(22,), name="decoder_input_layer")

embedding_layer = Embedding(num_decoder_tokens, word_embedding_size, mask_zero=True, name="embedding_layer")
embedding_outputs = embedding_layer(decoder_inputs)

decoder_lstm_name="decoder_lstm_"
decoder_lstm_0 = LSTM(latent_dim, return_sequences=True, return_state=True, name=decoder_lstm_name+"0")
decoder_outputs_0, _, _ = decoder_lstm_0(embedding_outputs, initial_state=encoder_states)
decoder_lstm_1 = LSTM(latent_dim, return_sequences=True, return_state=True, name=decoder_lstm_name+"1")
decoder_outputs_1,_,_ = decoder_lstm_1(decoder_outputs_0)
decoder_lstm_2 = LSTM(latent_dim, return_sequences=True, return_state=True, name=decoder_lstm_name+"2")
decoder_outputs_2, _, _ = decoder_lstm_1(decoder_outputs_1)

decoder_dense = Dense(num_decoder_tokens, activation='softmax', name="dense_layer")
decoder_outputs = decoder_dense(decoder_outputs_2)

model = Model([encoder_inputs, decoder_inputs], decoder_outputs)

#optimizer = RMSprop(lr=learning_rate, rho=0.9, epsilon=1e-08, decay=0.0, clipvalue = gradient_clip_value)
optimizer = Adam(lr=learning_rate)
model.compile(optimizer = optimizer, loss='categorical_crossentropy')
checkpoint_name=start_time+"checkpoit.hdf5"
checkpointer = ModelCheckpoint(filepath='./checkpoints/'+checkpoint_name, verbose=1, save_best_only=True)
csv_logger = CSVLogger(start_time+".csv", separator=',', append=False)
model.fit_generator(generate_input(train_file,vocab_json, batch_size, is_captioning=False), verbose=2, steps_per_epoch = num_samples / batch_size, epochs = epochs,
                    validation_data=generate_input(valid_file,vocab_json,batch_size, is_captioning=False), validation_steps=valid_steps, callbacks=[checkpointer, csv_logger])

ts = time.time()
end_time = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H:%M:%S')

model.save('./trained_models/' + str(start_time)+"-"+ str(end_time)+':image_to_text.h5')
