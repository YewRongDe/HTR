from __future__ import division
from __future__ import print_function
 
import sys
import numpy as np
import tensorflow as tf
import os
 
class Model: 
    "minimalistic TF model for HTR"
 
    # model constants
    batchSize = 128
    imgSize = (128, 32)
    maxTextLen = 32
 
    def __init__(self, charList, mustRestore=False):
        "init model: add CNN, RNN and CTC and initialize TF"
        self.charList = charList
        self.mustRestore = mustRestore
        self.snapID = 0
 
        # Whether to use normalization over a batch or a population
        self.is_train = tf.placeholder(tf.bool, name='is_train')
 
        # input image batch
        self.inputImgs = tf.placeholder(tf.float32, shape=(None, Model.imgSize[0], Model.imgSize[1]))
 
        # setup CNN, RNN and CTC
        self.setupCNN()
        self.setupRNN()
        self.setupCTC()
 
        # setup optimizer to train NN
        self.batchesTrained = 0
        self.learningRate = tf.placeholder(tf.float32, shape=[])
        self.update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS) 
        with tf.control_dependencies(self.update_ops):
            self.optimizer = tf.train.RMSPropOptimizer(self.learningRate).minimize(self.loss)
 
        # initialize TF
        (self.sess, self.saver) = self.setupTF()
 
        self.training_loss_summary = tf.summary.scalar('loss', self.loss)
        self.writer = tf.summary.FileWriter(
           './logs', self.sess.graph)  # Tensorboard: Create writer
        self.merge = tf.summary.merge([self.training_loss_summary])  # Tensorboard: Merge
 
 
    def setupCNN(self):
        "create CNN layers and return output of these layers"
        cnnIn4d = tf.expand_dims(input=self.inputImgs, axis=3)
        pool = cnnIn4d
        with tf.name_scope('Conv_Pool_1'):
            kernel = tf.Variable(tf.truncated_normal([5, 5, 1, 32], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 2, 2, 1), (1, 2, 2, 1), 'VALID')
 
        # Second Layer: Conv (5x5) + Pool (1x2) - Output size: 400 x 16 x 128
        with tf.name_scope('Conv_Pool_2'):
            kernel = tf.Variable(tf.truncated_normal([5, 5, 32, 64], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 2, 2, 1), (1, 2, 2, 1), 'VALID')
 
        # Third Layer: Conv (3x3) + Pool (2x2) + Simple Batch Norm - Output size: 200 x 8 x 128
        with tf.name_scope('Conv_Pool_3'):
            kernel = tf.Variable(tf.truncated_normal([3, 3, 64, 128], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 1, 1, 1), (1, 1, 1, 1), 'VALID')
 
        # Fourth Layer: Conv (3x3) - Output size: 200 x 8 x 256
        with tf.name_scope('Conv_Pool_4'):
            kernel = tf.Variable(tf.truncated_normal([3, 3, 128, 128], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 1, 2, 1), (1, 1, 2, 1), 'VALID')
 
        # Fifth Layer: Conv (3x3) + Pool(2x2) - Output size: 100 x 4 x 256
        with tf.name_scope('Conv_Pool_5'):
            kernel = tf.Variable(tf.truncated_normal([3, 3, 128, 256], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 1, 2, 1), (1, 1, 2, 1), 'VALID')
 
        # Sixth Layer: Conv (3x3) + Pool(1x2) + Simple Batch Norm - Output size: 100 x 2 x 512
        with tf.name_scope('Conv_Pool_6'):
            kernel = tf.Variable(tf.truncated_normal([3, 3, 256, 256], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 1, 2, 1), (1, 1, 2, 1), 'VALID')


        # Seventh Layer: Conv (3x3) + Pool (1x2) - Output size: 100 x 1 x 512
        with tf.name_scope('Conv_Pool_7'):
            kernel = tf.Variable(tf.truncated_normal([3, 3, 256, 512], stddev=0.1))
            conv = tf.nn.conv2d(pool, kernel, padding='SAME', strides=(1, 1, 1, 1))
            conv_norm = tf.layers.batch_normalization(conv, training=self.is_train)
            learelu = tf.nn.leaky_relu(conv_norm)
            pool = tf.nn.max_pool(learelu, (1, 1, 1, 1), (1, 1, 1, 1), 'VALID')
 
        self.cnnOut4d = pool
 
 
    def setupRNN(self):
        "create RNN layers and return output of these layers"
        rnnIn3d = tf.squeeze(self.cnnOut4d, axis=[2])
 
        # basic cells which is used to build RNN
        numHidden = 512
        cells = [tf.contrib.rnn.LSTMCell(num_units=numHidden, state_is_tuple=True) for _ in range(2)] # 2 layers
 
        # stack basic cells
        stacked = tf.contrib.rnn.MultiRNNCell(cells, state_is_tuple=True)
 
        # bidirectional RNN
        # BxTxF -> BxTx2H
        ((fw, bw), _) = tf.nn.bidirectional_dynamic_rnn(cell_fw=stacked, cell_bw=stacked, inputs=rnnIn3d, dtype=rnnIn3d.dtype)
 
        # BxTxH + BxTxH -> BxTx2H -> BxTx1X2H
        concat = tf.expand_dims(tf.concat([fw, bw], 2), 2)
 
        # project output to chars (including blank): BxTx1x2H -> BxTx1xC -> BxTxC
        kernel = tf.Variable(tf.truncated_normal([1, 1, numHidden * 2, len(self.charList) + 1], stddev=0.1))
        self.rnnOut3d = tf.squeeze(tf.nn.atrous_conv2d(value=concat, filters=kernel, rate=1, padding='SAME'), axis=[2])
 
 
    def setupCTC(self):
        "create CTC loss and decoder and return them"
        # BxTxC -> TxBxC
        self.ctcIn3dTBC = tf.transpose(self.rnnOut3d, [1, 0, 2])
        # ground truth text as sparse tensor
        self.gtTexts = tf.SparseTensor(tf.placeholder(tf.int64, shape=[None, 2]) , tf.placeholder(tf.int32, [None]), tf.placeholder(tf.int64, [2]))
 
        # calc loss for batch
        self.seqLen = tf.placeholder(tf.int32, [None])
        self.loss = tf.reduce_mean(tf.nn.ctc_loss(labels=self.gtTexts, inputs=self.ctcIn3dTBC, sequence_length=self.seqLen, ctc_merge_repeated=True))
 
        # calc loss for each element to compute label probability
        self.savedCtcInput = tf.placeholder(tf.float32, shape=[Model.maxTextLen, None, len(self.charList) + 1])
        self.lossPerElement = tf.nn.ctc_loss(labels=self.gtTexts, inputs=self.savedCtcInput, sequence_length=self.seqLen, ctc_merge_repeated=True)
 
        self.decoder = tf.nn.ctc_greedy_decoder(inputs=self.ctcIn3dTBC, sequence_length=self.seqLen) 
 
 
    def setupTF(self):
        "initialize TF"
        print('Python: '+sys.version)
        print('Tensorflow: '+tf.__version__)
 
        sess=tf.Session() # TF session
 
        saver = tf.train.Saver(max_to_keep=1) # saver saves model to file
        modelDir = 'SimpleHTR/model/'
        latestSnapshot = tf.train.latest_checkpoint(modelDir) # is there a saved model?
 
        # if model must be restored (for inference), there must be a snapshot
        if self.mustRestore and not latestSnapshot:
            raise Exception('No saved model found in: ' + modelDir)
 
        # load saved model if available
        if latestSnapshot:
            print('Init with stored values from ' + latestSnapshot)
            saver.restore(sess, latestSnapshot)
        else:
            print('Init with new values')
            sess.run(tf.global_variables_initializer())
 
        return (sess,saver)
 
 
    def toSparse(self, texts):
        "put ground truth texts into sparse tensor for ctc_loss"
        indices = []
        values = []
        shape = [len(texts), 0] # last entry must be max(labelList[i])
 
        # go over all texts
        for (batchElement, text) in enumerate(texts):
            # convert to string of label (i.e. class-ids)
            labelStr = [self.charList.index(c) for c in text]
            # sparse tensor must have size of max. label-string
            if len(labelStr) > shape[1]:
                shape[1] = len(labelStr)
            # put each label into sparse tensor
            for (i, label) in enumerate(labelStr):
                indices.append([batchElement, i])
                values.append(label)
 
        return (indices, values, shape)
 
 
    def decoderOutputToText(self, ctcOutput, batchSize):
        "extract texts from output of CTC decoder"
 
        # contains string of labels for each batch element
        encodedLabelStrs = [[] for i in range(batchSize)]
 
        decoded=ctcOutput[0][0] 
 
        # go over all indices and save mapping: batch -> values
        idxDict = { b : [] for b in range(batchSize) }
        for (idx, idx2d) in enumerate(decoded.indices):
            label = decoded.values[idx]
            batchElement = idx2d[0] # index according to [b,t]
            encodedLabelStrs[batchElement].append(label)
 
        # map labels to chars for all batch elements
        return [str().join([self.charList[c] for c in labelStr]) for labelStr in encodedLabelStrs]
 
 
    def trainBatch(self, batch, batchNum):
        "feed a batch into the NN to train it"
        numBatchElements = len(batch.imgs)
        sparse = self.toSparse(batch.gtTexts)
        rate = 0.01 if self.batchesTrained < 10 else (0.001 if self.batchesTrained < 10000 else 0.0001) # decay learning rate
        evalList = [self.merge, self.optimizer, self.loss]
        feedDict = {self.inputImgs : batch.imgs, self.gtTexts : sparse , self.seqLen : [Model.maxTextLen] * numBatchElements, self.learningRate : rate, self.is_train: True}
        (loss_summary, _, lossVal) = self.sess.run(evalList, feedDict)
        #Tensorboard: Add loss_summary to writer
        self.writer.add_summary(loss_summary, batchNum)
        self.batchesTrained += 1
        return lossVal
 
 
    def inferBatch(self, batch, calcProbability=False, probabilityOfGT=False):
        "feed a batch into the NN to recognize the texts"
 
        # decode, optionally save RNN output
        numBatchElements = len(batch.imgs)
        evalRnnOutput = calcProbability
        evalList = [self.decoder] + ([self.ctcIn3dTBC] if evalRnnOutput else [])
        feedDict = {self.inputImgs : batch.imgs, self.seqLen : [Model.maxTextLen] * numBatchElements, self.is_train: False}
        evalRes = self.sess.run(evalList, feedDict)
        decoded = evalRes[0]
        texts = self.decoderOutputToText(decoded, numBatchElements)
 
        # feed RNN output and recognized text into CTC loss to compute labeling probability
        probs = None
        if calcProbability:
            sparse = self.toSparse(batch.gtTexts) if probabilityOfGT else self.toSparse(texts)
            ctcInput = evalRes[1]
            evalList = self.lossPerElement
            feedDict = {self.savedCtcInput : ctcInput, self.gtTexts : sparse, self.seqLen : [Model.maxTextLen] * numBatchElements, self.is_train: False}
            lossVals = self.sess.run(evalList, feedDict)
            probs = np.exp(-lossVals)
 
        return (texts, probs)
 
 
    def save(self):
        "save model to file"
        self.snapID += 1
        self.saver.save(self.sess, 'SimpleHTR/model/snapshot', global_step=self.snapID)